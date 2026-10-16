
import io
import re
import zipfile

import pandas as pd


# ==========================================
# 1. CONFIGURATION
# ==========================================

CIGAR_PREFIXES = (
    "Cuban Cigars->",
    "Davidoff Cigars->",
    "New World Cigars->",
)

REQUIRED_A = (
    "Barcode",
    "QTY",
    "Selling Price",
)

REQUIRED_B = (
    "ID",
    "Barcode",
    "Name",
    "Quantity",
    "Price",
    "Stock Status",
    "With Storehouse Management",
    "Product Attributes",
    "Categories",
    "Tags",
)


# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================

def _read_csv(source, label):
    """Read an uploaded CSV file, path, or bytes."""

    if isinstance(source, bytes):
        source = io.BytesIO(source)

    if hasattr(source, "seek"):
        source.seek(0)

    try:
        df = pd.read_csv(
            source,
            dtype={"Barcode": "string"},
            low_memory=False,
        )
    except (
        pd.errors.ParserError,
        pd.errors.EmptyDataError,
        UnicodeError,
    ) as exc:
        raise ValueError(
            f"Cannot read {label}: {exc}"
        ) from exc

    df.columns = df.columns.str.strip()
    return df


def _safe_filename(name):
    """Create a safe filename for category exports."""

    return (
        re.sub(
            r'[<>:"/\\|?*]',
            "_",
            name,
        ).strip().rstrip(".")
        or "no_name"
    )


def _category_prefix(category):
    """Extract the main category name."""

    if not category:
        return "no_name"

    return (
        str(category)
        .split("->", 1)[0]
        .strip()
        or "no_name"
    )


# ==========================================
# 3. MAIN PROCESSING FUNCTION
# ==========================================

def process_stock(sheet_a, sheet_b):
    """
    Process supplier and website stock files.

    Returns category CSV files, ZIP bytes,
    and processing summary for Streamlit.
    """

    # ======================================
    # 4. READ AND VALIDATE FILES
    # ======================================

    df_a = _read_csv(sheet_a, "Sheet A")
    df_b = _read_csv(sheet_b, "Sheet B")

    for label, df, required in (
        ("Sheet A", df_a, REQUIRED_A),
        ("Sheet B", df_b, REQUIRED_B),
    ):
        missing = [
            col for col in required
            if col not in df.columns
        ]

        if missing:
            raise ValueError(
                f"{label} is missing columns: "
                f"{', '.join(missing)}"
            )

    # ======================================
    # 5. CLEAN DATA
    # ======================================

    df_a["Barcode"] = (
        df_a["Barcode"]
        .fillna("")
        .str.strip()
    )

    df_b["Barcode"] = (
        df_b["Barcode"]
        .fillna("")
        .str.strip()
    )

    df_b["Name"] = (
        df_b["Name"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    # Keep supplier quantities unchanged
    # during stock processing.
    df_a["QTY"] = pd.to_numeric(
        df_a["QTY"],
        errors="coerce",
    ).fillna(0)

    df_a["Selling Price"] = pd.to_numeric(
        df_a["Selling Price"]
        .astype(str)
        .str.replace("£", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip(),
        errors="coerce",
    )

    # ======================================
    # 6. MATCH BARCODES
    # ======================================

    working_df = df_b.copy()

    matched_names = set()
    matched_barcodes = set()

    for _, supplier_row in df_a.iterrows():

        barcode = supplier_row["Barcode"]

        if not barcode:
            continue

        mask = (
            working_df["Barcode"]
            .eq(barcode)
            .fillna(False)
        )

        if not mask.any():
            continue

        matched_barcodes.add(barcode)

        # Include parent products and variations
        matched_names.update(
            working_df.loc[
                mask, "Name"
            ].tolist()
        )

        # Update stock quantity
        working_df.loc[
            mask, "Quantity"
        ] = supplier_row["QTY"]

        # Update price if valid
        if pd.notna(supplier_row["Selling Price"]):
            working_df.loc[
                mask, "Price"
            ] = supplier_row["Selling Price"]

    # Include the complete matched product family
    output_df = working_df[
        working_df["Name"].isin(matched_names)
    ].copy()

    adjusted_count = 0

    # ======================================
    # 7. STOCK MANAGEMENT
    # ======================================

    if not output_df.empty:

        output_df = (
            output_df
            .drop_duplicates(
                subset=["ID"],
                keep="first",
            )
            .copy()
        )

        output_df[
            "With Storehouse Management"
        ] = 1

        output_df["Quantity"] = pd.to_numeric(
            output_df["Quantity"],
            errors="coerce",
        ).fillna(0)

        output_df["Stock Status"] = (
            output_df["Quantity"].apply(
                lambda qty: (
                    "out_of_stock"
                    if qty == 0
                    else "in_stock"
                )
            )
        )

        # ==================================
        # 8. IDENTIFY MAIN PRODUCT CATEGORIES
        # ==================================

        attributes = (
            output_df["Product Attributes"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        main_product_mask = (
            attributes.eq("Quantity")
        )

        output_df["_CleanCategory"] = (
            output_df["Categories"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        main_category_rows = output_df[
            main_product_mask
            & output_df["_CleanCategory"].ne("")
        ]

        main_category_map = (
            main_category_rows
            .drop_duplicates(
                subset=["Name"],
                keep="first",
            )
            .set_index("Name")["_CleanCategory"]
            .to_dict()
        )

        family_category_rows = output_df[
            output_df["_CleanCategory"].ne("")
        ]

        family_category_map = (
            family_category_rows
            .drop_duplicates(
                subset=["Name"],
                keep="first",
            )
            .set_index("Name")["_CleanCategory"]
            .to_dict()
        )

        output_df["_FullCategory"] = (
            output_df["Name"].map(
                lambda name: (
                    main_category_map.get(name, "")
                    or family_category_map.get(name, "")
                )
            )
        )

        # ==================================
        # 9. CIGAR LOW-STOCK RULE
        # ==================================

        cigar_category_mask = (
            output_df["_FullCategory"]
            .str.startswith(CIGAR_PREFIXES)
        )

        special_edition_mask = (
            output_df["Tags"]
            .fillna("")
            .astype(str)
            .str.contains(
                "Special Edition",
                case=False,
                regex=False,
            )
        )

        adjustment_mask = (
            cigar_category_mask
            & output_df["Quantity"].le(3)
            & ~special_edition_mask
        )

        adjusted_count = int(
            adjustment_mask.sum()
        )

        output_df.loc[
            adjustment_mask,
            "Quantity",
        ] = 0

        output_df.loc[
            adjustment_mask,
            "Stock Status",
        ] = "out_of_stock"

        output_df.loc[
            adjustment_mask,
            "With Storehouse Management",
        ] = 1

        # ==================================
        # 10. CLEAR PARENT PRODUCT BARCODES
        # ==================================

        repeated_products = (
            output_df["Name"]
            .duplicated(keep=False)
        )

        output_df.loc[
            repeated_products & main_product_mask,
            "Barcode",
        ] = ""

        # ==================================
        # 11. ASSIGN EXPORT CATEGORIES
        # ==================================

        output_df["_ExportCategory"] = (
            output_df["_FullCategory"]
            .map(_category_prefix)
        )

        # ==================================
        # 12. SORT PRODUCTS
        # ==================================

        group_order = {
            "Cuban Cigars": 0,
            "Davidoff Cigars": 1,
            "New World Cigars": 2,
        }

        output_df["_GroupOrder"] = (
            output_df["_ExportCategory"]
            .map(group_order)
            .fillna(3)
        )

        output_df["_OriginalOrder"] = range(
            len(output_df)
        )

        output_df = (
            output_df
            .sort_values(
                by=[
                    "_GroupOrder",
                    "Quantity",
                    "_OriginalOrder",
                ],
                ascending=[
                    True,
                    False,
                    True,
                ],
                kind="stable",
            )
            .drop_duplicates(
                subset=["ID"],
                keep="first",
            )
            .reset_index(drop=True)
        )

    else:
        output_df["_ExportCategory"] = (
            pd.Series(dtype="string")
        )

    # ======================================
    # 13. GENERATE CATEGORY CSV FILES
    # ======================================

    files = {}
    summary = []
    seen_filenames = set()

    for category, group in output_df.groupby(
        "_ExportCategory",
        sort=True,
    ):

        filename = (
            f"{_safe_filename(category)}.csv"
        )

        if filename.casefold() in seen_filenames:
            raise ValueError(
                f"Duplicate CSV filename: {filename}"
            )

        seen_filenames.add(
            filename.casefold()
        )

        # Keep original website columns
        export_df = group.reindex(
            columns=df_b.columns
        ).copy()

        # ==================================
        # 14. NEGATIVE QUANTITY EXPORT FIX
        # ==================================
        #
        # Apply this rule ONLY when
        # generating the final CSV files.
        #
        # Negative quantity -> 0
        # Stock Status -> out_of_stock
        #
        # Other quantities and stock
        # statuses remain unchanged.
        # ==================================

        export_df["Quantity"] = pd.to_numeric(
            export_df["Quantity"],
            errors="coerce",
        ).fillna(0)

        negative_mask = (
            export_df["Quantity"] < 0
        )

        export_df.loc[
            negative_mask,
            "Quantity",
        ] = 0

        export_df.loc[
            negative_mask,
            "Stock Status",
        ] = "out_of_stock"

        # ==================================
        # 15. CONVERT TO CSV
        # ==================================

        csv_bytes = (
            export_df
            .to_csv(index=False)
            .encode("utf-8-sig")
        )

        files[filename] = csv_bytes

        summary.append({
            "Category": category,
            "File": filename,
            "Rows": len(export_df),
        })

    # ======================================
    # 16. CREATE ZIP DOWNLOAD
    # ======================================

    archive_buffer = io.BytesIO()

    with zipfile.ZipFile(
        archive_buffer,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:

        for filename, content in files.items():
            archive.writestr(
                filename,
                content,
            )

    # ======================================
    # 17. RETURN RESULTS TO STREAMLIT
    # ======================================

    return {
        "files": files,
        "zip_bytes": archive_buffer.getvalue(),
        "summary": summary,
        "total_rows": sum(
            item["Rows"]
            for item in summary
        ),
        "total_files": len(files),
        "matched_barcodes": len(
            matched_barcodes
        ),
        "cigar_rows_adjusted": adjusted_count,
    }
