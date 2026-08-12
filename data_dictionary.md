# Data Dictionary

All IDs are synthetic. Empty cells mean no value was provided in the mock data.

## `accounts.csv`

- `account_id`: Unique account ID.
- `account_name`: Fictional company/account name.
- `country`: Primary country.
- `region`: Broad operating region.
- `sector`: High-level sector.
- `subsector`: More specific industry area.
- `ownership_type`: Fictional ownership category.
- `membership_status`: Current synthetic membership status.
- `account_manager`: Fictional internal owner.
- `family_owned`: `yes`, `no`, or `unknown`.
- `business_description`: Short account description.
- `tags`: Semicolon-separated account themes.
- `sensitivity_level`: General handling label.

## `people.csv`

- `person_id`: Unique person ID.
- `full_name`: Fictional person name.
- `account_id`: Linked account ID, if applicable.
- `role_title`: Person's role.
- `relationship_to_company`: Family member, executive, adviser, internal staff, etc.
- `is_family_member`: `yes`, `no`, or `n/a`.
- `generation`: Family generation if relevant.
- `email`: Synthetic email address.
- `phone`: Synthetic phone value.
- `contact_visibility`: How contact details may be used.
- `bio_note`: Short fictional profile note.
- `sensitivity_level`: General handling label.

## `events.csv`

- `event_id`: Unique event ID.
- `event_name`: Fictional event name.
- `city`: Event city.
- `region`: Event region.
- `event_date`: ISO date.
- `event_type`: Dinner, forum, roundtable, visit, briefing, etc.
- `status`: Planned, confirmed, completed, etc.
- `description`: Short event description.

## `event_attendance.csv`

- `attendance_id`: Unique attendance record.
- `event_id`: Linked event ID.
- `person_id`: Linked person ID.
- `account_id`: Linked account ID, if applicable.
- `attendance_status`: Confirmed, waitlisted, declined, cancelled, invited.
- `attendee_category`: Member guest, staff, external speaker, non-member guest, host, etc.
- `rsvp_date`: Date of RSVP or status update.
- `source_id`: Source supporting this attendance record.
- `notes`: Short note.

## `activities.csv`

- `activity_id`: Unique activity record.
- `activity_date`: ISO date.
- `account_id`: Linked account ID.
- `person_id`: Linked person ID, if any.
- `activity_type`: Meeting note, event update, public update, research note, etc.
- `title`: Short title.
- `summary`: Summary of the activity.
- `region`: Region associated with the activity.
- `themes`: Semicolon-separated tags.
- `visibility`: `public`, `internal`, or `restricted`.
- `sensitivity_level`: Handling label.
- `source_id`: Source supporting the activity.

## `relationships.csv`

- `relationship_id`: Unique relationship record.
- `from_person_id`: Potential introducer or known person.
- `from_account_id`: Their linked account, if applicable.
- `to_person_id`: Target person, if specific.
- `to_account_id`: Target account.
- `relationship_type`: Type of link.
- `strength`: Strong, moderate, weak, or inferred.
- `basis`: Why this relationship may exist.
- `visibility`: Public, internal, or restricted.
- `source_id`: Source supporting the relationship.
- `notes`: Handling notes.

## `sources.csv`

- `source_id`: Unique source ID.
- `source_type`: Public news, company website, internal CRM note, event RSVP, meeting note, policy, etc.
- `title`: Fictional source title.
- `publisher_or_origin`: Fictional publisher, origin, or internal system.
- `publication_date`: ISO date.
- `url`: Fictional URL or internal reference.
- `excerpt`: Short source snippet.
- `reliability`: High, medium, low, or unverified.
- `visibility`: Public, internal, restricted, or policy.
