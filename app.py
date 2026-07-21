from datetime import datetime, timezone, tzinfo
from typing import cast
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from sqlalchemy.exc import IntegrityError

from db import check_db_connection, date_column_is_timezone_aware, delete_data, load_data, save_data, update_data
from plot import plot_data


def is_user_datetime_conflict(exc: Exception) -> bool:
    message = str(exc)
    return (
        "data_userid_date_uidx" in message
        or 'Key (UserId, Date)=' in message
        or 'duplicate key value violates unique constraint' in message
    )


def get_local_timezone() -> tzinfo:
    configured_tz = st.session_state.get("app_timezone")
    if configured_tz:
        try:
            return ZoneInfo(str(configured_tz))
        except Exception:
            pass

    secret_tz = st.secrets.get("APP_TIMEZONE") if hasattr(st, "secrets") else None
    if secret_tz:
        try:
            return ZoneInfo(str(secret_tz))
        except Exception:
            pass

    local_tzinfo = datetime.now().astimezone().tzinfo
    if local_tzinfo is not None:
        return local_tzinfo

    return timezone.utc


def render_timezone_selector() -> None:
    if "app_timezone" not in st.session_state:
        default_tz = "UTC"
        secret_tz = st.secrets.get("APP_TIMEZONE") if hasattr(st, "secrets") else None
        if secret_tz:
            default_tz = str(secret_tz)
        st.session_state["app_timezone"] = default_tz

    timezone_input = st.sidebar.text_input(
        "App timezone (IANA)",
        value=str(st.session_state["app_timezone"]),
        help="Example: America/New_York",
    ).strip()

    if timezone_input:
        try:
            ZoneInfo(timezone_input)
            st.session_state["app_timezone"] = timezone_input
        except Exception:
            st.sidebar.error("Invalid timezone. Example: America/New_York")


def local_datetime_to_db_iso(value: datetime, timezone_aware_column: bool) -> str:
    if not timezone_aware_column:
        return value.replace(microsecond=0).isoformat(sep=" ")

    local_tz = get_local_timezone()
    if value.tzinfo is None:
        value = value.replace(tzinfo=local_tz)
    else:
        value = value.astimezone(local_tz)

    return value.astimezone(timezone.utc).isoformat(sep=" ")


def to_local_editor_datetime(value: object, timezone_aware_column: bool) -> datetime:
    if timezone_aware_column:
        utc_value = pd.to_datetime(value, utc=True)
        local_value = utc_value.tz_convert(get_local_timezone())
        return local_value.tz_localize(None).to_pydatetime()

    # Timestamp-without-time-zone should be shown exactly as stored.
    return pd.to_datetime(value).to_pydatetime()


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


def render_user_selector() -> str:
    if "current_user" not in st.session_state:
        st.title("Blood Pressure Data")
        st.subheader("Select user")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("Jerry", type="primary", use_container_width=True):
                st.session_state["current_user"] = "Jerry"
                st.rerun()

        with col2:
            if st.button("Wanda", type="primary", use_container_width=True):
                st.session_state["current_user"] = "Wanda"
                st.rerun()

        st.stop()

    current_user = str(st.session_state["current_user"])
    st.sidebar.caption(f"Current user: {current_user}")
    timezone_label = datetime.now(get_local_timezone()).tzname() or "Local"
    st.sidebar.caption(f"Timezone: {timezone_label}")
    if st.sidebar.button("Switch user"):
        st.session_state.pop("current_user", None)
        st.rerun()

    return current_user


def render_add_entry_form(current_user: str, timezone_aware_column: bool) -> None:
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

    try:
        save_data(current_user, local_datetime_to_db_iso(entry_datetime, timezone_aware_column), upper, lower, bpm)
    except IntegrityError as exc:
        if is_user_datetime_conflict(exc):
            st.sidebar.error("An entry already exists for this user at the selected date/time.")
        else:
            st.sidebar.error("Unable to save data due to a database constraint.")
        return

    st.session_state["show_add_form"] = False
    request_editor_reset()
    st.rerun()


def normalize_entry_row(row: pd.Series) -> tuple[datetime, int, int, int]:
    return (
        pd.to_datetime(row["Date"]).to_pydatetime().replace(microsecond=0),
        int(row["Upper"]),
        int(row["Lower"]),
        int(row["BPM"]),
    )


def build_editor_dataframe(df: pd.DataFrame, timezone_aware_column: bool) -> pd.DataFrame:
    editor_df = df.copy()
    editor_df["Date"] = editor_df["Date"].map(lambda value: to_local_editor_datetime(value, timezone_aware_column))
    editor_df["Delete"] = False
    return editor_df


def save_editor_changes(
    current_user: str,
    edited_df: pd.DataFrame,
    original_df: pd.DataFrame,
    timezone_aware_column: bool,
) -> int:
    original_by_id = original_df.set_index("EntryId")
    edited_by_id = edited_df.set_index("EntryId")
    updated_count = 0

    for entry_id, edited_row in edited_by_id.iterrows():
        entry_id_int = cast(int, entry_id)
        original_row = cast(pd.Series, original_by_id.loc[entry_id_int])
        if normalize_entry_row(edited_row) == normalize_entry_row(original_row):
            continue

        entry_date_local, upper, lower, bpm = normalize_entry_row(edited_row)
        update_data(
            current_user,
            entry_id_int,
            local_datetime_to_db_iso(entry_date_local, timezone_aware_column),
            upper,
            lower,
            bpm,
        )
        updated_count += 1

    return updated_count


def get_delete_ids(edited_df: pd.DataFrame) -> list[int]:
    if "Delete" not in edited_df.columns:
        return []

    return [int(entry_id) for entry_id in edited_df.loc[edited_df["Delete"], "EntryId"].tolist()]


@st.dialog("Confirm delete")
def confirm_delete_dialog(current_user: str) -> None:
    delete_ids = st.session_state.get("pending_delete_ids", [])
    st.write(f"Delete {len(delete_ids)} selected entr{'y' if len(delete_ids) == 1 else 'ies'}?")
    confirm_col, cancel_col = st.columns(2)

    with confirm_col:
        if st.button("Delete", type="primary"):
            for entry_id in delete_ids:
                delete_data(current_user, int(entry_id))
            st.session_state["pending_delete_ids"] = []
            request_editor_reset()
            st.rerun()

    with cancel_col:
        if st.button("Cancel"):
            st.session_state["pending_delete_ids"] = []
            st.rerun()


def main():
    st.set_page_config(layout="wide")
    # if "DATABASE_URL" in st.secrets:
    #     st.write("Secret loaded:", st.secrets["DATABASE_URL"][:10] + "...")
    # else:
    #     st.error("DATABASE_URL not found in secrets!")
    # # st.markdown(
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

    render_timezone_selector()

    current_user = render_user_selector()
    timezone_aware_column = date_column_is_timezone_aware()

    df = load_data(current_user)
    df.sort_values('Date', inplace=True, ascending=False)

    st.title(f"Blood Pressure Data - {current_user}")
    render_add_entry_form(current_user, timezone_aware_column)
    st.write("Loaded Data:")
    apply_editor_reset()
    editor_df = build_editor_dataframe(df, timezone_aware_column)
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
        try:
            save_editor_changes(current_user, edited_df, editor_df, timezone_aware_column)
        except IntegrityError as exc:
            if is_user_datetime_conflict(exc):
                st.sidebar.error("Save failed: another entry for this user already uses that date/time.")
            else:
                st.sidebar.error("Save failed due to a database constraint.")
            return
        request_editor_reset()
        st.rerun()

    delete_ids = get_delete_ids(edited_df)
    if st.sidebar.button("Delete selected"):
        if not delete_ids:
            st.sidebar.warning("Check one or more Delete boxes first.")
        else:
            st.session_state["pending_delete_ids"] = delete_ids
            confirm_delete_dialog(current_user)

    if df.empty:
        st.info("No blood pressure entries available.")
        return

    st.write("Blood Pressure Plots:")
    fig = plot_data(editor_df.drop(columns=["Delete"]))
    st.pyplot(fig)



if __name__ == "__main__":
    main()