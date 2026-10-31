---
name: work-a-web-page
description: Fill in a form, sign up, book or order on a website, or click through a site to get something done.
triggers: fill in, form, website, sign up, register, book, order, click
---
1. open_url with the site's address (or web_search, then open_search_result).
2. look_at_page with {"only_controls": true}. Every button, link and box has a ref like e12.
3. type_in {"ref": "e12", "text": "..."} for each box; choose_option for dropdowns; click for buttons and links.
4. After each click you are shown the new page; read it before the next step.
5. Never type passwords, card numbers or codes: ask the person with pause_for_me.
6. Buttons that send, pay, book or delete ask the person first. Say what you are about to submit.
