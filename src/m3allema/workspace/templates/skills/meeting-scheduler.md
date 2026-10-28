---
description: Find a free slot and book a meeting, respecting working hours from BUSINESS.md.
---
1. Get the attendees, length and preferred days. Ask if any are missing.
2. List the owner's events for those days with `calendar__list_events`.
3. Pick up to three free slots inside working hours, with 15 minutes around other meetings.
4. Show the slots to the owner and wait for a choice.
5. Create the event with `calendar__create_event`, adding attendees only after the owner
   confirmed the slot. Include a one-line agenda in the description.
6. Reply with the booked time, the attendees and the event link.
