import os
from flask import Flask
from jobs.gather_events import run_city_events_job
from jobs.generate_suggestions import run_new_users_job, run_suggestions_job
from apscheduler.schedulers.background import BackgroundScheduler

def _start_scheduler(app: Flask) -> None:
    '''
    Start the APScheduler to run the suggestions job daily at 07:30 AM Athens time.
    '''
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    sched = BackgroundScheduler(timezone="Europe/Athens", daemon=True)

    sched.add_job(
        run_suggestions_job,
        trigger="cron",
        hour=5, minute=30,
        id="daily_suggestions",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=120,
        args=[app]
    )

    sched.add_job(
        run_city_events_job,
        "cron",
        hour=4, minute=30,               
        args=[app],
        id="city_events_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    sched.add_job(
        run_new_users_job,
        trigger="interval",
        minutes=10,
        id="bootstrap_new_users",
        args=[app],
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    
    sched.start()
    app.logger.info("Scheduler started: daily_suggestions")
    app.logger.info("Scheduler started: run_city_events_job")
    app.logger.info("Scheduler started: bootstrap_new_users")