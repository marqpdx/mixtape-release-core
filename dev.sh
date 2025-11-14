#!/bin/bash
# Development server startup script for mixtape-release-core
# Runs Django on port 8010

cd app
../env/bin/python manage.py runserver 8010
