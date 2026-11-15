---
name: ui-check
description: Check a page or UI change in the running app at 375 px and 1280 px, light and dark, on a test account with sample watch data. Use for /ui-check or before calling any UI work done.
---

Check the page or change named in the user's message.

## Steps

1. Run the app (`uv run uvicorn app.main:app --port 8000`) and sign in with a test account
   that uses **sample watch data** (setup step 1). Never check UI on a real person's data.
2. For each of 375 px and 1280 px, light and dark:
   - open the page, take a screenshot, read the text;
   - check `document.documentElement.scrollWidth` equals the viewport width (no sideways
     scroll);
   - look for: cut-off text, buttons that look enabled but are disabled, two primary actions,
     mixed languages, numbers without units, helper text that repeats the label.
3. Switch the language to Ukrainian once and check the page has no English left
   (`app/i18n_uk.json` for missing strings).
4. Click every new control once: it does something visible, shows a loading state if it takes
   more than a second, and shows an error with a next step if it fails.
5. Follow `docs/design-guidelines.md`: one accent colour for the main action, plain words,
   no gradients or emoji icons.

## Report back

- What was checked (pages × sizes × themes × languages).
- Defects with the file and line to fix.
- What was not checked (real phone, push notifications, real photos).
