import logging
import time
import typing

from dbnd._core.constants import DbndTargetOperationType
from dbnd._core.plugin.dbnd_plugins import is_plugin_enabled
from dbnd._core.task_run.task_run_tracker import TaskRunTracker
from dbnd._core.tracking.log_data_reqeust import LogDataRequest
from dbnd._core.utils import seven
from targets.value_meta import ValueMetaConf


if typing.TYPE_CHECKING:
    from datetime import datetime
    from typing import Optional, Union, List, Dict, Any
    import pandas as pd
    import pyspark.sql as spark

    from dbnd_postgres.postgres_values import PostgresTable
    from dbnd_snowflake.snowflake_values import SnowflakeTable

logger = logging.getLogger(__name__)


def _get_tracker():
    # type: ()-> Optional[TaskRunTracker]
    from dbnd._core.task_run.current_task_run import try_get_or_create_task_run

    task_run = try_get_or_create_task_run()
    if task_run:
        return task_run.tracker
    return None


def log_data(
    key,  # type: str
    value=None,  # type: Union[pd.DataFrame, spark.DataFrame, PostgresTable, SnowflakeTable]
    path=None,  # type: Optional[str]
    operation_type=DbndTargetOperationType.read,  # type: DbndTargetOperationType
    with_preview=True,  # type: Optional[bool]
    with_size=True,  # type: Optional[bool]
    with_schema=True,  # type: Optional[bool]
    with_stats=False,  # type: Optional[Union[bool, str, List[str], LogDataRequest]]
    with_histograms=False,  # type: Optional[Union[bool, str, List[str], LogDataRequest]]
):  # type: (...) -> None
    tracker = _get_tracker()
    if not tracker:
        return

    meta_conf = ValueMetaConf(
        log_preview=with_preview,
        log_schema=with_schema,
        log_size=with_size,
        log_stats=with_stats,
        log_histograms=with_histograms,
    )

    tracker.log_data(
        key, value, meta_conf=meta_conf, path=path, operation_type=operation_type
    )


log_dataframe = log_data


def log_pg_table(
    table_name,
    connection_string,
    with_preview=True,
    with_schema=True,
    with_histograms=False,  # type: Union[LogDataRequest, bool, str, List[str]]
):

    try:
        if not is_plugin_enabled("dbnd-postgres", module_import="dbnd_postgres"):
            return
        from dbnd_postgres import postgres_values

        pg_table = postgres_values.PostgresTable(table_name, connection_string)
        log_data(
            table_name,
            pg_table,
            with_preview=with_preview,
            with_schema=with_schema,
            with_histograms=with_histograms,
        )
    except Exception:
        logger.exception("Failed to log_pg_table")


def log_snowflake_table(
    table_name,  # type: str
    connection_string,  # type: str
    database,  # type: str
    schema,  # type: str
    with_preview=True,
    with_schema=True,
):

    try:
        if not is_plugin_enabled("dbnd-snowflake", module_import="dbnd_snowflake"):
            return
        from dbnd_snowflake import snowflake_values

        with log_duration("log_snowflake_table__time_seconds", source="system"):
            conn_params = snowflake_values.conn_str_to_conn_params(connection_string)
            account = conn_params["account"]
            user = conn_params["user"]
            password = conn_params["password"]

            snowflake_table = snowflake_values.SnowflakeTable(
                account, user, password, database, schema, table_name
            )

        log_data(
            table_name,
            snowflake_table,
            with_preview=with_preview,
            with_schema=with_schema,
            with_histograms=False,
        )
    except Exception as ex:
        logger.exception("Failed to log_snowflake_table")


def log_metric(key, value, source="user"):
    tracker = _get_tracker()
    if tracker:
        tracker.log_metric(key, value, source=source)
        return

    logger.info("Log {} Metric '{}'='{}'".format(source.capitalize(), key, value))


def log_metrics(metrics_dict, source="user", timestamp=None):
    # type: (Dict[str, Any], str, datetime) -> None
    tracker = _get_tracker()
    if tracker:
        from dbnd._core.tracking.schemas.metrics import Metric
        from dbnd._core.utils.timezone import utcnow

        metrics = [
            Metric(key=key, value=value, source=source, timestamp=timestamp or utcnow())
            for key, value in metrics_dict.items()
        ]
        tracker._log_metrics(metrics)


def log_artifact(key, artifact):
    tracker = _get_tracker()
    if tracker:
        tracker.log_artifact(key, artifact)
        return

    logger.info("Artifact %s=%s", key, artifact)


@seven.contextlib.contextmanager
def log_duration(metric_key, source="user"):
    """
    Measure time of function or code block, and log to Databand as a metric.
    Can be used as a decorator and in "with" statement as a context manager.

    Example 1:
        @log_duration("f_time_duration")
        def f():
            sleep(1)

    Example 2:
        with log_duration("my_code_duration"):
            sleep(1)
    """
    start_time = time.time()
    try:
        yield
    finally:
        end_time = time.time()
        log_metric(metric_key, end_time - start_time, source)
