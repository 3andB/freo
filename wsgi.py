from app import create_app
from sqlalchemy.orm import configure_mappers
from app.services.schedule import validate_timezone
from app.services.timezones import choices as timezone_choices

app = create_app()

# Gunicorn loads this entry point before serving requests. Do read-only lazy
# initialization here so first-use request threads cannot stampede the IANA
# filesystem scan or queue behind mapper configuration. No DB is opened.
configure_mappers()
validate_timezone('UTC')
timezone_choices()
