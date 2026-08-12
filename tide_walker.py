import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

print("DEBUG: Script imports completed successfully")

# ============ YOUR SETTINGS ============
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

TIDE_URL = "https://www.tidetime.org/europe/united-kingdom/river-hamble.htm"

# Explicitly use UK local time
LONDON = ZoneInfo("Europe/London")

# Walking rules
WALK_OFFSET_HOURS = 2
AVAILABLE_START_HOUR = 6
AVAILABLE_END_HOUR = 20

# Number of days to show
DAYS_TO_SHOW = 7

# Ignore tiny fragments of walking windows
MIN_WINDOW_MINUTES = 30
# ========================================


def get_high_tides():
    """
    Fetch fully dated high tides from TideTime.

    TideTime embeds high-tide times in its page as Unix timestamps:

        var highTides = [....];

    Because each timestamp contains both date AND time,
    we no longer need to guess which day a tide belongs to.
    """

    try:
        print(f"   Connecting to {TIDE_URL}...")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-GB,en;q=0.9",
            "Connection": "keep-alive",
        }

        response = requests.get(
            TIDE_URL,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()

        # ---------------------------------------------------------
        # Extract TideTime's highTides JavaScript timestamp array
        # ---------------------------------------------------------

        match = re.search(
            r"(?:var\s+)?highTides\s*=\s*\[([^\]]+)\]",
            response.text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if not match:
            raise ValueError(
                "Could not find TideTime's highTides timestamp array. "
                "The TideTime page format may have changed."
            )

        timestamps = [
            int(value)
            for value in re.findall(
                r"\b\d{9,11}\b",
                match.group(1)
            )
        ]

        if len(timestamps) < 2:
            raise ValueError(
                f"Only found {len(timestamps)} high-tide timestamp(s); "
                "expected at least 2."
            )

        # ---------------------------------------------------------
        # Convert Unix timestamps directly to UK local datetimes
        # ---------------------------------------------------------

        high_tides = sorted(
            set(
                datetime.fromtimestamp(
                    timestamp,
                    tz=LONDON
                )
                for timestamp in timestamps
            )
        )

        print(
            f"   ✅ Found {len(high_tides)} "
            f"unique dated high tides"
        )

        # ---------------------------------------------------------
        # Print tides around the forecast period for debugging
        # ---------------------------------------------------------

        now = datetime.now(LONDON)

        today = now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        debug_start = today - timedelta(days=1)

        debug_end = today + timedelta(
            days=DAYS_TO_SHOW + 1
        )

        print("   High tides around forecast period:")

        for tide in high_tides:

            if debug_start <= tide <= debug_end:

                print(
                    "      "
                    + tide.strftime(
                        "%a %d %b %Y %I:%M%p"
                    )
                )

        # ---------------------------------------------------------
        # Sanity check
        # ---------------------------------------------------------

        forecast_end = today + timedelta(
            days=DAYS_TO_SHOW
        )

        if (
            high_tides[-1] < today
            or high_tides[0] > forecast_end
        ):
            raise ValueError(
                "TideTime returned high tides, but they do not "
                "overlap the current 7-day forecast period. "
                "Refusing to calculate potentially incorrect windows."
            )

        return high_tides

    except Exception as e:

        print(
            f"   ❌ Error fetching tide data: {e}"
        )

        return None


def calculate_walking_windows(high_tides):
    """
    Calculate walking windows between consecutive high tides.

    For each pair of consecutive high tides:

        start = current high tide + 2 hours
        end   = next high tide - 2 hours

    Each resulting window is then clipped to
    6am-8pm for each calendar day.

    This works even where a calendar day contains
    only one high tide.
    """

    now = datetime.now(LONDON)

    today = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    raw_windows = []

    # -------------------------------------------------------------
    # STEP 1:
    # Make walking windows between consecutive HIGH tides
    # -------------------------------------------------------------

    for i in range(len(high_tides) - 1):

        hi = high_tides[i]

        hi_next = high_tides[i + 1]

        # Safe walking starts two hours AFTER high tide
        walk_start = hi + timedelta(
            hours=WALK_OFFSET_HOURS
        )

        # Safe walking ends two hours BEFORE next high tide
        walk_end = hi_next - timedelta(
            hours=WALK_OFFSET_HOURS
        )

        # Only keep genuine windows
        if walk_end > walk_start:

            raw_windows.append(
                {
                    "start": walk_start,
                    "end": walk_end,
                    "previous_high": hi,
                    "next_high": hi_next,
                }
            )

    print(
        f"   Calculated {len(raw_windows)} "
        f"raw walking windows"
    )

    # -------------------------------------------------------------
    # STEP 2:
    # Clip each window to 6am-8pm
    # -------------------------------------------------------------

    result = []

    for window in raw_windows:

        start_day = window["start"].replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        end_day = window["end"].replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        current_day = start_day

        while current_day <= end_day:

            day_offset = (
                current_day.date()
                - today.date()
            ).days

            # Only show today + next 6 days
            if 0 <= day_offset < DAYS_TO_SHOW:

                day_avail_start = current_day.replace(
                    hour=AVAILABLE_START_HOUR,
                    minute=0,
                    second=0,
                    microsecond=0,
                )

                day_avail_end = current_day.replace(
                    hour=AVAILABLE_END_HOUR,
                    minute=0,
                    second=0,
                    microsecond=0,
                )

                # Clip walking window to 6am-8pm
                clipped_start = max(
                    window["start"],
                    day_avail_start
                )

                clipped_end = min(
                    window["end"],
                    day_avail_end
                )

                duration_minutes = (
                    clipped_end - clipped_start
                ).total_seconds() / 60

                # Only add if there is at least
                # 30 minutes of walking time
                if duration_minutes >= MIN_WINDOW_MINUTES:

                    result.append(
                        {
                            "start": clipped_start,
                            "end": clipped_end,
                            "day_offset": day_offset,
                        }
                    )

            current_day += timedelta(days=1)

    # -------------------------------------------------------------
    # STEP 3:
    # Sort results and remove any duplicates
    # -------------------------------------------------------------

    result.sort(
        key=lambda window: window["start"]
    )

    unique_result = []

    seen = set()

    for window in result:

        key = (
            window["start"],
            window["end"]
        )

        if key not in seen:

            seen.add(key)

            unique_result.append(window)

    print(
        f"   Calculated {len(unique_result)} "
        f"clipped walking windows"
    )

    return unique_result


def format_email_body(walking_windows):
    """
    Create the HTML email containing walking windows.
    """

    html = """
    <html>
    <body style="
        font-family: Arial, sans-serif;
        padding: 20px;
        background-color: #f5f5f5;
    ">

        <div style="
            max-width: 600px;
            margin: 0 auto;
            background-color: white;
            border-radius: 10px;
            padding: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        ">

            <h1 style="
                color: #2c5aa0;
                text-align: center;
                border-bottom: 3px solid #2c5aa0;
                padding-bottom: 15px;
            ">
                🌊 River Hamble Walking Times 🌊
            </h1>
    """

    # -------------------------------------------------------------
    # No walking windows
    # -------------------------------------------------------------

    if not walking_windows:

        html += """
            <p style="
                color: #d32f2f;
                font-size: 16px;
            ">
                ⚠️ No valid walking windows were calculated.
                <br><br>

                Please check the tide data manually at:
                <br>

                <a href="
                https://www.tidetime.org/europe/united-kingdom/river-hamble.htm
                ">
                    tidetime.org/europe/united-kingdom/river-hamble.htm
                </a>
            </p>
        """

    else:

        now = datetime.now(LONDON)

        today = now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        # ---------------------------------------------------------
        # Group walking windows by day
        # ---------------------------------------------------------

        windows_by_day = {}

        for window in walking_windows:

            day_offset = window["day_offset"]

            windows_by_day.setdefault(
                day_offset,
                []
            ).append(window)

        # ---------------------------------------------------------
        # Display each day
        # ---------------------------------------------------------

        for day_offset in sorted(
            windows_by_day.keys()
        ):

            day_date = today + timedelta(
                days=day_offset
            )

            day_windows = sorted(
                windows_by_day[day_offset],
                key=lambda window: window["start"],
            )

            html += f"""
            <div style="
                margin: 20px 0;
                padding: 15px;
                background-color: #e3f2fd;
                border-left: 4px solid #2c5aa0;
                border-radius: 5px;
            ">

                <h3 style="
                    color: #1976d2;
                    margin: 0 0 10px 0;
                ">
                    📅 {day_date.strftime('%A, %d %B')}
                </h3>
            """

            # -----------------------------------------------------
            # Display walking windows
            # -----------------------------------------------------

            for i, window in enumerate(
                day_windows
            ):

                if len(day_windows) > 1:
                    window_label = f"W {i + 1}: "
                else:
                    window_label = ""

                start_time = window[
                    "start"
                ].strftime(
                    "%I:%M%p"
                ).lower()

                end_time = window[
                    "end"
                ].strftime(
                    "%I:%M%p"
                ).lower()

                html += f"""
                <p style="
                    font-size: 18px;
                    margin: 5px 0;
                    color: #333;
                ">

                    <strong>
                        {window_label}
                    </strong>

                    {start_time} - {end_time}

                </p>
                """

            html += """
            </div>
            """

    # -------------------------------------------------------------
    # Footer
    # -------------------------------------------------------------

    generated_time = datetime.now(
        LONDON
    ).strftime(
        "%d/%m/%Y at %H:%M"
    )

    html += f"""
            <div style="
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #ddd;
                text-align: center;
                color: #666;
            ">

                <p>
                    🚶 Enjoy your riverside walks!
                </p>

                <p style="
                    font-size: 11px;
                    color: #999;
                ">

                    Walking windows between consecutive
                    high tides
                    (+{WALK_OFFSET_HOURS}hrs /
                    -{WALK_OFFSET_HOURS}hrs)

                    <br>

                    Clipped to available hours:
                    {AVAILABLE_START_HOUR}:00 -
                    {AVAILABLE_END_HOUR}:00

                    <br>

                    Tide dates/times read directly
                    from TideTime timestamp data

                </p>

                <p style="
                    font-size: 12px;
                ">
                    Generated: {generated_time}
                </p>

            </div>

        </div>

    </body>
    </html>
    """

    return html


def send_email(subject, body_html):
    """
    Send HTML email via Gmail SMTP.
    """

    try:

        # ---------------------------------------------------------
        # Create email
        # ---------------------------------------------------------

        msg = MIMEMultipart(
            "alternative"
        )

        msg["Subject"] = subject

        msg["From"] = GMAIL_ADDRESS

        msg["To"] = RECIPIENT_EMAIL

        # Attach HTML
        html_part = MIMEText(
            body_html,
            "html"
        )

        msg.attach(html_part)

        # ---------------------------------------------------------
        # Connect to Gmail
        # ---------------------------------------------------------

        print(
            "   Connecting to Gmail..."
        )

        server = smtplib.SMTP(
            "smtp.gmail.com",
            587
        )

        server.starttls()

        # ---------------------------------------------------------
        # Login
        # ---------------------------------------------------------

        print(
            "   Logging in..."
        )

        password = (
            GMAIL_APP_PASSWORD.replace(
                " ",
                ""
            )
        )

        server.login(
            GMAIL_ADDRESS,
            password
        )

        # ---------------------------------------------------------
        # Send email
        # ---------------------------------------------------------

        print(
            "   Sending email..."
        )

        server.send_message(msg)

        server.quit()

        print(
            "   ✅ Email sent successfully!"
        )

        return True

    except Exception as e:

        print(
            f"   ❌ Error sending email: {e}"
        )

        return False


def send_error_email(error_message):
    """
    Send an error email rather than silently
    returning potentially incorrect walking times.
    """

    subject = (
        "⚠️ River Hamble Tide Data - Error"
    )

    body = f"""
    <html>

    <body style="
        font-family: Arial, sans-serif;
        padding: 20px;
    ">

        <h2>
            ⚠️ River Hamble Tide Walker Error
        </h2>

        <p>
            The script could not safely calculate
            the walking windows.
        </p>

        <p>
            <strong>Error:</strong>
            {error_message}
        </p>

        <p>
            Please check the tides manually at:

            <br>

            <a href="{TIDE_URL}">
                {TIDE_URL}
            </a>
        </p>

    </body>

    </html>
    """

    send_email(
        subject,
        body
    )


def main():
    """
    Main function.
    """

    print(
        "\n"
        + "=" * 60
    )

    print(
        "🌊 RIVER HAMBLE TIDE WALKER 🌊".center(
            60
        )
    )

    print(
        "=" * 60
    )

    # -------------------------------------------------------------
    # Check environment variables
    # -------------------------------------------------------------

    print(
        "\n🔐 Checking environment variables..."
    )

    print(
        f"Gmail address: {GMAIL_ADDRESS}"
    )

    print(
        f"Recipient: {RECIPIENT_EMAIL}"
    )

    print(
        "Password loaded: "
        + (
            "Yes"
            if GMAIL_APP_PASSWORD
            else "No"
        )
    )

    if not all(
        [
            GMAIL_ADDRESS,
            GMAIL_APP_PASSWORD,
            RECIPIENT_EMAIL,
        ]
    ):

        print(
            "❌ Missing environment variables!"
        )

        return

    # -------------------------------------------------------------
    # STEP 1:
    # Fetch fully dated high tides
    # -------------------------------------------------------------

    print(
        "\n📡 STEP 1: "
        "Fetching dated high-tide data..."
    )

    high_tides = get_high_tides()

    if not high_tides:

        print(
            "   ❌ Could not safely fetch "
            "high-tide data"
        )

        print(
            "\n📧 Sending error notification..."
        )

        send_error_email(
            "Unable to extract valid dated "
            "high tides from TideTime."
        )

        return

    # -------------------------------------------------------------
    # STEP 2:
    # Calculate walking windows
    # -------------------------------------------------------------

    print(
        "\n🧮 STEP 2: "
        "Calculating walking windows..."
    )

    walking_windows = (
        calculate_walking_windows(
            high_tides
        )
    )

    if not walking_windows:

        print(
            "   ❌ No valid walking windows "
            "were calculated"
        )

        print(
            "\n📧 Sending error notification..."
        )

        send_error_email(
            "High tides were fetched, "
            "but no valid walking windows "
            "could be calculated."
        )

        return

    # -------------------------------------------------------------
    # STEP 3:
    # Format email
    # -------------------------------------------------------------

    print(
        "\n📝 STEP 3: "
        "Formatting email..."
    )

    today_string = datetime.now(
        LONDON
    ).strftime(
        "%d %B %Y"
    )

    subject = (
        "🌊 River Hamble Walking Times "
        f"- Week of {today_string}"
    )

    body_html = format_email_body(
        walking_windows
    )

    print(
        "   ✅ Email formatted"
    )

    # -------------------------------------------------------------
    # STEP 4:
    # Send email
    # -------------------------------------------------------------

    print(
        "\n📧 STEP 4: "
        "Sending email..."
    )

    success = send_email(
        subject,
        body_html
    )

    if success:

        print(
            "\n"
            + "=" * 60
        )

        print(
            f"✅ SUCCESS! "
            f"Check your email at "
            f"{RECIPIENT_EMAIL}"
        )

        print(
            "=" * 60
            + "\n"
        )

    else:

        print(
            "\n"
            + "=" * 60
        )

        print(
            "❌ FAILED - "
            "Check error messages above"
        )

        print(
            "=" * 60
            + "\n"
        )


if __name__ == "__main__":
    main()
