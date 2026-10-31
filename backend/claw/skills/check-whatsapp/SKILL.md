---
name: check-whatsapp
description: Check WhatsApp Desktop for unread chats, or send a WhatsApp message with approval.
triggers: whatsapp, unread, chats, messages
---
1. check_whatsapp opens WhatsApp Desktop if needed and lists unread chats.
2. If it says WhatsApp is not installed or not linked, tell the person exactly that and stop. Do not try again.
3. To send, use send_whatsapp_message; the person approves it before it is sent.
