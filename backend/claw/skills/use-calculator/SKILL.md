---
name: use-calculator
description: Work out a sum in the Windows Calculator app.
triggers: calculator, calc
---
1. Call launch_app with name "Calculator".
2. Type the whole sum at once with type_text, using * for times and / for divide, and end with =. For example: 1234*56=
3. Call look_at_window and read the result from the control whose name starts with "Display is".
4. Give that number as the answer. Do not click the digit buttons one by one.
