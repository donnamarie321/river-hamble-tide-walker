import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ============ YOUR SETTINGS ============
import os
GMAIL_ADDRESS = os.getenv('GMAIL_ADDRESS')
GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD') 
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')
# ========================================

def get_tide_data():
    """Scrapes tide data from tidetime.org for River Hamble"""
    url = "https://www.tidetime.org/europe/united-kingdom/river-hamble.htm"
    
    try:
        print(f"   Connecting to {url}...")
        
        # Add headers to look like a real browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-GB,en;q=0.9',
            'Connection': 'keep-alive',
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        tide_data = []
        
        # Pattern to match tide entries like "High 5:17am" or "Low 9:44am"
        text_content = soup.get_text()
        pattern = r'(High|Low)\s+(\d{1,2}):(\d{2})(am|pm)?'
        matches = re.finditer(pattern, text_content, re.IGNORECASE)
        
        for match in matches:
            tide_type = match.group(1).capitalize()
            hour = match.group(2)
            minute = match.group(3)
            period = match.group(4) if match.group(4) else ''
            tide_time = f"{hour}:{minute}{period}"
            
            tide_data.append({
                'type': tide_type,
                'time': tide_time
            })
        
        return tide_data if len(tide_data) > 0 else None
    
    except Exception as e:
        print(f"   ❌ Error fetching tide data: {e}")
        return None

def parse_time_with_date(time_str, base_date):
    """Convert time string to datetime object with proper date handling"""
    try:
        time_str = time_str.strip().lower()
        
        is_pm = 'pm' in time_str
        is_am = 'am' in time_str
        time_str = time_str.replace('am', '').replace('pm', '').strip()
        
        parts = time_str.split(':')
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        
        # Convert to 24-hour format
        if is_pm and hour != 12:
            hour += 12
        elif is_am and hour == 12:
            hour = 0
            
        return base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except Exception as e:
        return None

def calculate_walking_windows(tide_data):
    """
    Calculate walking windows based on consecutive high tides.
    For each pair (Hi, Hi+1): walking window is (Hi+2h) to (Hi+1-2h)
    Then clip to availability hours (6am-8pm) and group by day.
    """
    
    # Step 1: Extract and sort all HIGH tides chronologically
    now = datetime.now()
    current_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    high_tides = []
    
    # Parse high tides, inferring dates based on sequence
    for i, tide in enumerate(tide_data):
        if tide['type'] == 'High':
            # Start with current date, increment as we see tides go backwards in time
            tide_time = parse_time_with_date(tide['time'], current_date)
            
            if tide_time:
                # If this tide is earlier than the last one, it must be next day
                if high_tides and tide_time < high_tides[-1]:
                    current_date += timedelta(days=1)
                    tide_time = parse_time_with_date(tide['time'], current_date)
                
                high_tides.append(tide_time)
    
    # Remove duplicates and sort
    high_tides = sorted(list(set(high_tides)))
    
    print(f"   Found {len(high_tides)} unique high tides")
    if high_tides:
        print(f"   First: {high_tides[0].strftime('%a %d %b %I:%M%p')}")
        print(f"   Last: {high_tides[-1].strftime('%a %d %b %I:%M%p')}")
    
    # Step 2: For each consecutive pair of high tides, calculate raw walking window
    raw_windows = []
    for i in range(len(high_tides) - 1):
        hi = high_tides[i]
        hi_next = high_tides[i + 1]
        
        # Raw walking window: Hi + 2h to Hi+1 - 2h
        walk_start = hi + timedelta(hours=2)
        walk_end = hi_next - timedelta(hours=2)
        
        # Only include if valid
        if walk_end > walk_start:
            raw_windows.append({
                'start': walk_start,
                'end': walk_end
            })
    
    print(f"   Calculated {len(raw_windows)} raw walking windows")
    
    # Step 3: Clip to availability (6am-8pm) and group by day
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    result = []
    
    for window in raw_windows:
        # Determine which days this window spans
        start_day = window['start'].replace(hour=0, minute=0, second=0, microsecond=0)
        end_day = window['end'].replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Process each day in the range
        current_day = start_day
        while current_day <= end_day:
            day_offset = (current_day - today).days
            
            # Only include next 7 days
            if 0 <= day_offset < 7:
                # Define this day's availability window
                day_avail_start = current_day.replace(hour=6, minute=0)  # 6am
                day_avail_end = current_day.replace(hour=20, minute=0)   # 8pm
                
                # Clip the walking window to this day's availability
                clipped_start = max(window['start'], day_avail_start)
                clipped_end = min(window['end'], day_avail_end)
                
                # Only add if there's actual time available (minimum 30 minutes)
                duration_minutes = (clipped_end - clipped_start).total_seconds() / 60
                if duration_minutes >= 30:
                    result.append({
                        'start': clipped_start,
                        'end': clipped_end,
                        'day_offset': day_offset
                    })
            
            current_day += timedelta(days=1)
    
    return result

def format_email_body(walking_windows):
    """Create a nice HTML email with walking times"""
    html = """
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5;">
        <div style="max-width: 600px; margin: 0 auto; background-color: white; border-radius: 10px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <h1 style="color: #2c5aa0; text-align: center; border-bottom: 3px solid #2c5aa0; padding-bottom: 15px;">
                🌊 River Hamble Walking Times 🌊
            </h1>
    """
    
    if not walking_windows or len(walking_windows) == 0:
        html += """
            <p style="color: #d32f2f; font-size: 16px;">
                ⚠️ Unable to fetch tide data. Please check manually at:<br>
                <a href="https://www.tidetime.org/europe/united-kingdom/river-hamble.htm">
                    tidetime.org/europe/united-kingdom/river-hamble.htm
                </a>
            </p>
        """
    else:
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        today = datetime.now()
        
        # Group windows by day
        windows_by_day = {}
        for window in walking_windows:
            day_offset = window['day_offset']
            if day_offset not in windows_by_day:
                windows_by_day[day_offset] = []
            windows_by_day[day_offset].append(window)
        
        # Display each day
        for day_offset in sorted(windows_by_day.keys()):
            day_date = today + timedelta(days=day_offset)
            day_name = days[day_date.weekday()]
            day_windows = windows_by_day[day_offset]
            
            html += f"""
            <div style="margin: 20px 0; padding: 15px; background-color: #e3f2fd; border-left: 4px solid #2c5aa0; border-radius: 5px;">
                <h3 style="color: #1976d2; margin: 0 0 10px 0;">
                    📅 {day_name}, {day_date.strftime('%d %B')}
                </h3>
            """
            
            # Display all windows for this day
            for i, window in enumerate(day_windows):
                window_label = f"W {i+1}: " if len(day_windows) > 1 else ""
                html += f"""
                <p style="font-size: 18px; margin: 5px 0; color: #333;">
                    <strong>{window_label}</strong>{window['start'].strftime('%I:%M%p').lower()} - {window['end'].strftime('%I:%M%p').lower()}
                </p>
                """
            
            html += """
            </div>
            """
    
    html += f"""
            <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; text-align: center; color: #666;">
                <p>🚶 Enjoy your riverside walks!</p>
                <p style="font-size: 11px; color: #999;">
                    Walking windows between consecutive high tides (+2hrs/-2hrs)<br>
                    Clipped to available hours: 6am - 8pm
                </p>
                <p style="font-size: 12px;">Generated: {datetime.now().strftime('%d/%m/%Y at %H:%M')}</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html

def send_email(subject, body_html):
    """Send email via Gmail SMTP"""
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = GMAIL_ADDRESS
        msg['To'] = RECIPIENT_EMAIL
        
        # Attach HTML body
        html_part = MIMEText(body_html, 'html')
        msg.attach(html_part)
        
        # Connect to Gmail SMTP
        print("   Connecting to Gmail...")
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        
        # Login (remove spaces from password)
        print("   Logging in...")
        password = GMAIL_APP_PASSWORD.replace(' ', '')
        server.login(GMAIL_ADDRESS, password)
        
        # Send email
        print("   Sending email...")
        server.send_message(msg)
        server.quit()
        
        print("   ✅ Email sent successfully!")
        return True
        
    except Exception as e:
        print(f"   ❌ Error sending email: {e}")
        return False

def main():
    """Main function"""
    print("\n" + "=" * 60)
    print("🌊 RIVER HAMBLE TIDE WALKER 🌊".center(60))
    print("=" * 60)
    
    # Step 1: Get tide data
    print("\n📡 STEP 1: Fetching tide data...")
    tide_data = get_tide_data()
    
    if not tide_data:
        print("   ❌ Could not fetch tide data")
        print("\n📧 Sending error notification...")
        subject = "⚠️ River Hamble Tide Data - Error"
        body = "<p>Unable to fetch tide data. Please check manually.</p>"
        send_email(subject, body)
        return
    
    print(f"   ✅ Found {len(tide_data)} tide entries")
    
    # Step 2: Calculate walking windows
    print("\n🧮 STEP 2: Calculating walking windows...")
    walking_windows = calculate_walking_windows(tide_data)
    print(f"   ✅ Calculated {len(walking_windows)} walking windows")
    
    # Step 3: Format email
    print("\n📝 STEP 3: Formatting email...")
    subject = f"🌊 River Hamble Walking Times - Week of {datetime.now().strftime('%d %B %Y')}"
    body_html = format_email_body(walking_windows)
    print("   ✅ Email formatted")
    
    # Step 4: Send email
    print("\n📧 STEP 4: Sending email...")
    success = send_email(subject, body_html)
    
    if success:
        print("\n" + "=" * 60)
        print("✅ SUCCESS! Check your email at " + RECIPIENT_EMAIL)
        print("=" * 60 + "\n")
    else:
        print("\n" + "=" * 60)
        print("❌ FAILED - Check error messages above")
        print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
