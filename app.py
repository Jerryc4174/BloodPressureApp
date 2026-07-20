from datetime import datetime
from typing import cast

import pandas as pd
import streamlit as st

from db import check_db_connection, delete_data, load_data, save_data, update_data
from plot import plot_data


def request_editor_reset() -> None:
    st.session_state["clear_blood_pressure_editor"] = True


def apply_editor_reset() -> None:
    if st.session_state.pop("clear_blood_pressure_editor", False):
        st.session_state.pop("blood_pressure_editor", None)


def ensure_add_form_state() -> None:
    if "add_form_date" in st.session_state:
        return

    now = datetime.now().replace(second=0, microsecond=0)
    st.session_state["add_form_date"] = now.date()
    st.session_state["add_form_time"] = now.time()
    st.session_state["add_form_upper"] = ""
    st.session_state["add_form_lower"] = ""
    st.session_state["add_form_bpm"] = ""


def render_add_entry_form() -> None:
    if st.sidebar.button("Add data"):
        st.session_state["show_add_form"] = True
        ensure_add_form_state()

    if not st.session_state.get("show_add_form", False):
        return

    ensure_add_form_state()
    st.sidebar.subheader("Add data")

    with st.sidebar.form("add_entry_form"):
        st.date_input("Date", key="add_form_date")
        st.time_input("Time", key="add_form_time")
        st.text_input("Upper Blood Pressure", key="add_form_upper")
        st.text_input("Lower Blood Pressure", key="add_form_lower")
        st.text_input("BPM", key="add_form_bpm")
        submitted = st.form_submit_button("Save")
        cancelled = st.form_submit_button("Cancel")

    if cancelled:
        st.session_state["show_add_form"] = False
        st.rerun()

    if not submitted:
        return

    try:
        entry_datetime = datetime.combine(st.session_state["add_form_date"], st.session_state["add_form_time"])
        upper = int(st.session_state["add_form_upper"])
        lower = int(st.session_state["add_form_lower"])
        bpm = int(st.session_state["add_form_bpm"])
    except ValueError:
        st.sidebar.error("Upper Blood Pressure, Lower Blood Pressure, and BPM must be whole numbers.")
        return

    save_data(entry_datetime.isoformat(sep=" "), upper, lower, bpm)
    st.session_state["show_add_form"] = False
    request_editor_reset()
    st.rerun()


def normalize_entry_row(row: pd.Series) -> tuple[str, int, int, int]:
    return (
        pd.to_datetime(row["Date"]).isoformat(sep=" "),
        int(row["Upper"]),
        int(row["Lower"]),
        int(row["BPM"]),
    )


def build_editor_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    editor_df = df.copy()
    editor_df["Date"] = pd.to_datetime(editor_df["Date"])
    editor_df["Delete"] = False
    return editor_df


def save_editor_changes(edited_df: pd.DataFrame, original_df: pd.DataFrame) -> int:
    original_by_id = original_df.set_index("EntryId")
    edited_by_id = edited_df.set_index("EntryId")
    updated_count = 0

    for entry_id, edited_row in edited_by_id.iterrows():
        entry_id_int = cast(int, entry_id)
        original_row = cast(pd.Series, original_by_id.loc[entry_id_int])
        if normalize_entry_row(edited_row) == normalize_entry_row(original_row):
            continue

        entry_date, upper, lower, bpm = normalize_entry_row(edited_row)
        update_data(entry_id_int, entry_date, upper, lower, bpm)
        updated_count += 1

    return updated_count


def get_delete_ids(edited_df: pd.DataFrame) -> list[int]:
    if "Delete" not in edited_df.columns:
        return []

    return [int(entry_id) for entry_id in edited_df.loc[edited_df["Delete"], "EntryId"].tolist()]


@st.dialog("Confirm delete")
def confirm_delete_dialog() -> None:
    delete_ids = st.session_state.get("pending_delete_ids", [])
    st.write(f"Delete {len(delete_ids)} selected entr{'y' if len(delete_ids) == 1 else 'ies'}?")
    confirm_col, cancel_col = st.columns(2)

    with confirm_col:
        if st.button("Delete", type="primary"):
            for entry_id in delete_ids:
                delete_data(int(entry_id))
            st.session_state["pending_delete_ids"] = []
            request_editor_reset()
            st.rerun()

    with cancel_col:
        if st.button("Cancel"):
            st.session_state["pending_delete_ids"] = []
            st.rerun()


def main():
    st.set_page_config(layout="wide")
    # st.markdown(
    #     """
    #     <style>
    #         .st-key-blood_pressure_editor [data-testid="stDataFrame"] {
    #             zoom: 1.25;
    #         }

    #         @supports not (zoom: 1.25) {
    #             .st-key-blood_pressure_editor [data-testid="stDataFrame"] {
    #                 transform: scale(1.25);
    #                 transform-origin: top left;
    #                 width: 80%;
    #                 margin-bottom: 180px;
    #                 font-size: 36px;
    #             }
    #         }
    #     </style>
    #     """,
    #     unsafe_allow_html=True,
    # )

    db_ok, db_message = check_db_connection()
    if db_ok:
        st.sidebar.success(db_message)
    else:
        st.sidebar.error(db_message)
        st.stop()

    df = load_data()
    df.sort_values('Date', inplace=True, ascending=False)

    st.title("Blood Pressure Data")
    render_add_entry_form()
    st.write("Loaded Data:")
    apply_editor_reset()
    editor_df = build_editor_dataframe(df)
    edited_df = st.data_editor(
        editor_df,
        hide_index=True,
        key="blood_pressure_editor",
        width="stretch",
        column_config={
            "EntryId": None,
            "Date": st.column_config.DatetimeColumn("Date", format="YYYY-MM-DD HH:mm", width="medium"),
            "Upper": st.column_config.NumberColumn("Upper", width="small"),
            "Lower": st.column_config.NumberColumn("Lower", width="small"),
            "BPM": st.column_config.NumberColumn("BPM", width="small"),
            "Delete": st.column_config.CheckboxColumn("Delete Select", width="small"),
        },
        disabled=["EntryId"],
        num_rows="fixed",
        row_height=70,
    )

    if st.sidebar.button("Save changes"):
        save_editor_changes(edited_df, df)
        request_editor_reset()
        st.rerun()

    delete_ids = get_delete_ids(edited_df)
    if st.sidebar.button("Delete selected"):
        if not delete_ids:
            st.sidebar.warning("Check one or more Delete boxes first.")
        else:
            st.session_state["pending_delete_ids"] = delete_ids
            confirm_delete_dialog()

    if df.empty:
        st.info("No blood pressure entries available.")
        return

    st.write("Blood Pressure Plots:")
    fig = plot_data(df)
    st.pyplot(fig)



if __name__ == "__main__":
    main()