from datetime import datetime, timezone, tzinfo
from calendar import monthrange
from typing import cast
from zoneinfo import ZoneInfo, available_timezones

import pandas as pd
import streamlit as st
from sqlalchemy.exc import IntegrityError

from db import check_db_connection, delete_data, load_data, save_data, update_data
from plot import plot_data


MIN_UPPER = 75
MAX_UPPER = 250
MIN_LOWER = 40
MAX_LOWER = 150
MIN_BPM = 20
MAX_BPM = 150


def subtract_months(value: datetime, months: int) -> datetime:
    year = value.year
    month = value.month - months

    while month <= 0:
        month += 12
        year -= 1

    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def get_entry_datetime_bounds() -> tuple[datetime, datetime]:
    now_local = datetime.now(get_local_timezone()).replace(tzinfo=None)
    min_allowed = subtract_months(now_local, 6)
    return min_allowed, now_local


def validate_entry_values(entry_datetime: datetime, upper: int, lower: int, bpm: int) -> str | None:
    min_allowed, max_allowed = get_entry_datetime_bounds()

    if entry_datetime < min_allowed or entry_datetime > max_allowed:
        return (
            "Date/time must be between "
            f"{min_allowed.strftime('%Y-%m-%d %H:%M')} and {max_allowed.strftime('%Y-%m-%d %H:%M')}."
        )

    if upper < MIN_UPPER or upper > MAX_UPPER:
        return f"Upper Blood Pressure must be between {MIN_UPPER} and {MAX_UPPER}."

    if lower < MIN_LOWER or lower > MAX_LOWER:
        return f"Lower Blood Pressure must be between {MIN_LOWER} and {MAX_LOWER}."

    if bpm < MIN_BPM or bpm > MAX_BPM:
        return f"BPM must be between {MIN_BPM} and {MAX_BPM}."

    return None


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


def get_app_timezone_name() -> str:
    configured_tz = st.session_state.get("app_timezone")
    if configured_tz:
        return str(configured_tz)

    local_tz = get_local_timezone()
    tz_key = getattr(local_tz, "key", None)
    if tz_key:
        return str(tz_key)

    return "UTC"


def render_timezone_selector() -> None:
    america_timezones = sorted(tz for tz in available_timezones() if tz.startswith("America/"))
    if not america_timezones:
        america_timezones = ["America/New_York"]

    if "app_timezone" not in st.session_state:
        default_tz = "America/New_York"
        secret_tz = st.secrets.get("APP_TIMEZONE") if hasattr(st, "secrets") else None
        if secret_tz and str(secret_tz) in america_timezones:
            default_tz = str(secret_tz)
        st.session_state["app_timezone"] = default_tz

    current_tz = str(st.session_state.get("app_timezone", "America/New_York"))
    if current_tz not in america_timezones:
        current_tz = "America/New_York"
        st.session_state["app_timezone"] = current_tz

    current_index = america_timezones.index(current_tz)
    selected_tz = st.sidebar.selectbox(
        "App timezone",
        options=america_timezones,
        index=current_index,
        help="Select an America/* timezone.",
    )
    st.session_state["app_timezone"] = selected_tz


def local_datetime_to_db_iso(value: datetime, timezone_aware_column: bool) -> str:
    _ = timezone_aware_column
    return value.replace(microsecond=0).isoformat(sep=" ")


def to_local_editor_datetime(value: object, timezone_aware_column: bool) -> datetime:
    _ = timezone_aware_column
    return pd.to_datetime(value).to_pydatetime()


def request_editor_reset() -> None:
    st.session_state["clear_blood_pressure_editor"] = True


def apply_editor_reset() -> None:
    if st.session_state.pop("clear_blood_pressure_editor", False):
        st.session_state.pop("blood_pressure_editor", None)


def ensure_add_form_state() -> None:
    if "add_form_date" in st.session_state:
        return

    now = datetime.now(get_local_timezone()).replace(second=0, microsecond=0, tzinfo=None)
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


def render_add_entry_form(current_user: str, app_timezone_name: str, timezone_aware_column: bool) -> None:
    if st.sidebar.button("Add data"):
        st.session_state["show_add_form"] = True
        ensure_add_form_state()

    if not st.session_state.get("show_add_form", False):
        return

    ensure_add_form_state()
    st.sidebar.subheader("Add data")

    min_allowed, max_allowed = get_entry_datetime_bounds()
    min_allowed_date = min_allowed.date()
    max_allowed_date = max_allowed.date()

    if st.session_state["add_form_date"] < min_allowed_date:
        st.session_state["add_form_date"] = min_allowed_date
    if st.session_state["add_form_date"] > max_allowed_date:
        st.session_state["add_form_date"] = max_allowed_date

    with st.sidebar.form("add_entry_form"):
        st.date_input("Date", key="add_form_date", min_value=min_allowed_date, max_value=max_allowed_date)
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

    validation_error = validate_entry_values(entry_datetime, upper, lower, bpm)
    if validation_error:
        st.sidebar.error(validation_error)
        return

    try:
        save_data(
            current_user,
            local_datetime_to_db_iso(entry_datetime, timezone_aware_column),
            upper,
            lower,
            bpm,
            app_timezone=app_timezone_name,
        )
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
    app_timezone_name: str,
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
        validation_error = validate_entry_values(entry_date_local, upper, lower, bpm)
        if validation_error:
            raise ValueError(f"Row with EntryId {entry_id_int}: {validation_error}")

        update_data(
            current_user,
            entry_id_int,
            local_datetime_to_db_iso(entry_date_local, timezone_aware_column),
            upper,
            lower,
            bpm,
            app_timezone=app_timezone_name,
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
    app_timezone_name = get_app_timezone_name()
    timezone_aware_column = True

    df = load_data(current_user, app_timezone=app_timezone_name)
    df.sort_values('Date', inplace=True, ascending=False)

    st.title(f"Blood Pressure Data - {current_user}")
    render_add_entry_form(current_user, app_timezone_name, timezone_aware_column)
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
            save_editor_changes(current_user, app_timezone_name, edited_df, editor_df, timezone_aware_column)
        except ValueError as exc:
            st.sidebar.error(str(exc))
            return
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