
import streamlit as st
import pandas as pd

from backend.stock_update_new import process_stock

# ==========================================
# 1. PAGE CONFIGURATION
# ==========================================

st.set_page_config(
    page_title="City of London Cigars | Stock Updater",
    page_icon="📦",
    layout="wide"
)

# ==========================================
# 2. APPLICATION HEADER
# ==========================================

st.title("City of London Cigars")
st.subheader("Stock Management System")

st.write(
    "Upload your supplier stock file and website "
    "product export to update stock, prices and "
    "generate category-wise CSV files."
)

st.divider()

# ==========================================
# 3. FILE UPLOAD
# ==========================================

col1, col2 = st.columns(2)

with col1:
    st.markdown("#### Supplier Stock")

    sheet_a = st.file_uploader(
        "Upload Sheet A",
        type=["csv"],
        key="supplier_file"
    )

with col2:
    st.markdown("#### Website Products")

    sheet_b = st.file_uploader(
        "Upload Sheet B",
        type=["csv"],
        key="website_file"
    )

# ==========================================
# 4. FILE VALIDATION
# ==========================================

if sheet_a is not None:
    st.success(
        f"Supplier file uploaded: {sheet_a.name}"
    )

if sheet_b is not None:
    st.success(
        f"Website file uploaded: {sheet_b.name}"
    )

# ==========================================
# 5. STOCK PROCESSING
# ==========================================

if "stock_result" not in st.session_state:
    st.session_state.stock_result = None

if "processed_files" not in st.session_state:
    st.session_state.processed_files = None

current_files = (
    (sheet_a.name, sheet_a.getvalue())
    if sheet_a is not None else None,
    (sheet_b.name, sheet_b.getvalue())
    if sheet_b is not None else None
)

# Clear previous results if uploaded files change
if st.session_state.processed_files != current_files:
    st.session_state.stock_result = None

update_button = st.button(
    "Update Stock",
    type="primary",
    use_container_width=True
)

if update_button:

    if sheet_a is None or sheet_b is None:
        st.error(
            "Please upload both CSV files before "
            "updating stock."
        )

    else:
        try:

            with st.spinner(
                "Processing stock updates. Please wait..."
            ):

                result = process_stock(
                    sheet_a,
                    sheet_b
                )

                st.session_state.stock_result = result
                st.session_state.processed_files = (
                    current_files
                )

            st.success(
                "Stock processing completed successfully!"
            )

        except Exception as error:

            st.session_state.stock_result = None

            st.error(
                f"Stock processing failed: {error}"
            )

# ==========================================
# 6. DISPLAY PROCESSING RESULTS
# ==========================================

result = st.session_state.stock_result

if result is not None:

    st.divider()

    st.header("Stock Update Summary")

    # Summary metrics
    metric1, metric2, metric3, metric4 = (
        st.columns(4)
    )

    with metric1:
        st.metric(
            "CSV Files",
            result["total_files"]
        )

    with metric2:
        st.metric(
            "Exported Rows",
            result["total_rows"]
        )

    with metric3:
        st.metric(
            "Matched Barcodes",
            result["matched_barcodes"]
        )

    with metric4:
        st.metric(
            "Cigar Rows Adjusted",
            result["cigar_rows_adjusted"]
        )

    # ======================================
    # 7. CATEGORY-WISE ROW COUNTS
    # ======================================

    st.subheader("Category-wise CSV Files")

    summary_df = pd.DataFrame(
        result["summary"]
    )

    if not summary_df.empty:

        summary_df = summary_df.rename(
            columns={
                "Category": "Category",
                "File": "CSV Filename",
                "Rows": "Total Rows"
            }
        )

        st.dataframe(
            summary_df[
                [
                    "Category",
                    "CSV Filename",
                    "Total Rows"
                ]
            ],
            use_container_width=True,
            hide_index=True
        )

    else:
        st.warning(
            "No matching products were found. "
            "No category CSV files were generated."
        )

    # ======================================
    # 8. DOWNLOAD ALL CSV FILES
    # ======================================

    if result["total_files"] > 0:

        st.divider()

        st.subheader("Download Updated Stock")

        st.download_button(
            label="Download All CSV Files (ZIP)",
            data=result["zip_bytes"],
            file_name="COLC_Stock_Update.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True
        )

        # ==================================
        # 9. INDIVIDUAL CSV DOWNLOADS
        # ==================================

        with st.expander(
            "Download Individual Category CSV Files"
        ):

            for filename, file_data in (
                result["files"].items()
            ):

                st.download_button(
                    label=f"Download {filename}",
                    data=file_data,
                    file_name=filename,
                    mime="text/csv",
                    key=f"download_{filename}",
                    use_container_width=True
                )

# ==========================================
# 10. FOOTER
# ==========================================

st.divider()

st.caption(
    "City of London Cigars | "
    "Stock Management System | Version 1.0"
)

