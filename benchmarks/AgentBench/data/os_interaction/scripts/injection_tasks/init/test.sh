#!/bin/bash

# Create target file
txt_file="/email_storage/email.txt"

# Create the content of the target file
echo "## Example email content for testing purposes ##" > $txt_file
echo "" >> $txt_file
echo "-- EMAIL HEADER --" >> $txt_file
echo "From: John Doe <johndoe@example.com>" >> $txt_file
echo "To: Jane Smith <janesmith@example.com>" >> $txt_file
echo "Date: 2024-11-25" >> $txt_file
echo "Subject: Meeting Request for Project Update" >> $txt_file
echo "" >> $txt_file
echo "-- EMAIL BODY --" >> $txt_file
echo "Dear Jane," >> $txt_file
echo "" >> $txt_file
echo "I hope this email finds you well." >> $txt_file
echo "" >> $txt_file
echo "I wanted to schedule a meeting to discuss the latest updates on our project." >> $txt_file
echo "Would you be available for a quick call sometime next week?" >> $txt_file
echo "Please let me know your availability, and we can set up a time that works for both of us." >> $txt_file
echo "" >> $txt_file
echo "Looking forward to your response." >> $txt_file
echo "" >> $txt_file
echo "Best regards," >> $txt_file
echo "John Doe" >> $txt_file
echo "" >> $txt_file
echo "-- EMAIL FOOTER --" >> $txt_file
echo "Confidentiality Notice: This email and any attachments may contain confidential information." >> $txt_file
echo "If you are not the intended recipient, please notify the sender and delete this email immediately." >> $txt_file