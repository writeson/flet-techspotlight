# Flet Tech Spotlight Database Design #

The flet tech spotlight application is a demonstration application to show how to use Python to create GUI applications that are both powerful and cross-platform.

There are two parts to the system:

1) The primary Flet application (using Flet version 1.0.4) that displays a semi-realtime heatmap of payment information graphically by state and by zip code on a United States map.
2) A background asyncio Python application to runs continuously to populate a Sqlite database with payment information used to populate the Flet displayed heat-map.

## Database Table

1) Use sqlite for the database that supports WAL and asynchronous access between two applications
   1) Database stored in repository data/heatmap_data.db file
2) Create a table named "payments" with the following properties
   1) Created_at timestamps are recorded as Unix Epoch values
   2) Payment amount information is stored as integers (cents)
   3) Payment location information is stored in this manner:
      1) By zipcode
      2) By two-character state abreviation
      3) By full name state name

## Backend Application

The backend application runs continuously to populate the the payments table with data. It does this in this manner:

1) The backend application is an Python asyncio application
2) The application use SqlModel (https://github.com/fastapi/sqlmodel) to interact with the database
3) The application updates the payments table every 5 seconds
4) When it runs it creates a batch of payment objects/records. That update will follow this pattern:
   1) Each record will have an Unix Epoch timestamps that ranges randomly over the entire 5 second window
   2) The payment amount will range randomly from 100 to 10000 
   3) The payment records will gather around the 9:00 to 5:00 timerange using a bell curve. The 9:00 to 5:00 timerange will be plus/minus centered on the current time so the distribution follows the clock time across the united states
   4) The payment records generated with be weighted to generate more of them in more populous states and zip codes

## Project Layout and Running the System

The repository is split into three independent uv projects, each with its own
`pyproject.toml`, `uv.lock`, and virtual environment (`.venv`):

- `backend/tools` — the generator described above
- `ui/src` — the Flet application
- `ui/tests` — the Flet application's pytest suite

See `README.md` ("Project layout" and "Heatmap data") for the commands to
install, run, and test each part.





