def main():
    """Main function"""
    print("\n" + "=" * 60)
    print("🌊 RIVER HAMBLE TIDE WALKER 🌊".center(60))
    print("=" * 60)
    
    # Check environment variables first
    print("\n🔐 Checking environment variables...")
    print(f"Gmail address: {GMAIL_ADDRESS}")
    print(f"Recipient: {RECIPIENT_EMAIL}")
    print(f"Password loaded: {'Yes' if GMAIL_APP_PASSWORD else 'No'}")
    
    if not all([GMAIL_ADDRESS, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL]):
        print("❌ Missing environment variables!")
        return
    
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
        print(f"✅ SUCCESS! Check your email at {RECIPIENT_EMAIL}")
        print("=" * 60 + "\n")
    else:
        print("\n" + "=" * 60)
        print("❌ FAILED - Check error messages above")
        print("=" * 60 + "\n")
