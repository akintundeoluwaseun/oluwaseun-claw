# One agent, not a drawer full of integrations

S-CLAW does not integrate with WhatsApp, or Telegram, or Instagram, or Gmail. It
operates the computer. Those apps already run on it, so there is nothing to
integrate with — there is a Start menu to open, a window to focus, a box to type
in, and a Send button that waits for a person.

That is the whole design, and it is why the capability list stays short while
the things it can do keep growing:

```
open the app  →  look at what is on screen  →  do one step  →  check it worked
      ↑                                                              │
      └──────────────── if something needs you, stop and ask ────────┘
```

## What that means in practice

**"Open Telegram and message John."** `launch_app` finds Telegram in the Start
menu, or — new — switches to it if it is already open and has no shortcut, which
is the case for Store apps and anything only pinned to the taskbar.
`look_at_window` reads the accessibility tree, `click_control` opens the chat,
`type_text` writes the message, and pressing Enter needs your approval because
Enter is how that app sends.

**"Open Instagram in Chrome and message John."** Same thing in a browser. This
is where a real gap was: the rule that makes Enter count as *sending* looked at
the program, and in a browser the program is only ever `chrome.exe`. So the rule
now reads the window title as well — Instagram, WhatsApp Web, Telegram Web,
Gmail, Outlook, LinkedIn, Messenger, Discord, Slack. Enter on an ordinary page
is still ordinary.

A false positive there costs one extra approval. A false negative sends a
message nobody approved, which is why the rule errs towards asking.

And the asking itself has to be worth something. `press_keys: ["enter"]` is a
true description of the step and tells you nothing, so the approval card for a
send now names the chat it is going to — read from the window title — and quotes
the message that is about to leave:

> This sends the message to 'John Doe' in telegram.exe.
> The message reads: "Running late - I will be there at 2."

If nothing was typed in this task, it says that instead of quoting an older
message, because the one thing worse than a vague approval is a confident wrong
one.

**"Draft an e-mail to the supplier about the quote."** `compose_mail` opens a
compose window — Gmail, Outlook on the web, or whatever Windows has set as the
default mail program — with the recipients, subject and body already written.
**It never sends.** There is no IMAP client and no stored mailbox password,
because the browser is already signed in and a tool that could both write and
send is one bad sentence away from mailing the wrong person.

**"Remind me about the site visit on Tuesday."** That is the calendar —
`create_event`, `list_events`, `find_free_time`, `cancel_event` — stored as
`.ics` so Outlook, Google and any CalDAV server can read it.

And it does remind you. The reminder is written into the file as a real
`VALARM`, so every other calendar program rings it too, and S-CLAW itself
checks once a minute and raises a Windows notification. Three rules decide
what you actually see:

- **Once.** What was shown is recorded beside the calendars, so a reminder
  never arrives twice.
- **Not a pile.** If the laptop was off for a week, reminders whose moment
  passed more than an hour ago are retired without being shown. Ten
  notifications for things that already happened is how people learn to
  ignore the real one.
- **Never a guess.** A repeating event (`RRULE`) is skipped, because nothing
  here works out its occurrences, and a reminder on the wrong day is worse
  than none. An all-day event counts from 09:00, not from midnight.

**A password, a code, a CAPTCHA.** `pause_for_me` stops the task, says exactly
what is needed, sends a notification so you know even if you have walked away,
and carries on from where it stopped. S-CLAW never types the credential and
never reads it.

## Why not build an integration per app

An integration means an API key, a stored password, or an unofficial client that
breaks when the service changes — three things to maintain per app, each with
its own way of going wrong, and for WhatsApp specifically a terms-of-service
risk to the account. Operating the app the person already has signed in needs
none of that, works the day a new app appears, and leaves every Send button
under a human's finger.

The cost is honest too: it only works while the person's own computer is on and
unlocked, it is slower than an API, and it depends on the app's accessibility
tree being readable. Those are real limits and they are not hidden anywhere.

## What is still only tested against a stand-in

Everything above is tested — 47 tests on these paths alone — but the desktop
half runs against `tests/fake_desktop.py`, a labelled test double, because this
build container has no Windows desktop. **That is logic, not Windows.**
`docs/WINDOWS_ACCEPTANCE.md` is the list of what a real machine has to confirm.
