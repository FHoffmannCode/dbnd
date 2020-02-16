import logging
import subprocess
import time
import typing

from dbnd._core.plugin.dbnd_plugins import assert_plugin_enabled
from dbnd._core.task_run.task_engine_ctrl import TaskEnginePolicyCtrl
from dbnd._core.utils.basics.cmd_line_builder import CmdLineBuilder
from dbnd._core.utils.basics.text_banner import TextBanner
from dbnd._core.utils.structures import list_of_strings
from dbnd_qubole import QuboleConfig
from dbnd_qubole.errors import failed_to_run_qubole_job
from dbnd_spark.spark_ctrl import SparkCtrl
from qds_sdk.commands import SparkCommand
from qds_sdk.qubole import Qubole


if typing.TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def get_cloud_sync(config, task, job):
    assert_plugin_enabled("dbnd-aws", "qubole on aws requires dbnd-aws module.")


class QuboleCtrl(SparkCtrl):
    def __init__(self, task_run):
        super(QuboleCtrl, self).__init__(task_run=task_run)
        self.qubole_config = task_run.task.spark_engine  # type: QuboleConfig

        self.qubole_cmd_id = None
        self.qubole_job_url = None

        Qubole.configure(
            api_token=self.qubole_config.api_token,
            api_url=self.qubole_config.api_url,
            cloud_name=self.qubole_config.cloud,
        )

        self._setup_qubole_loggers()

    def _setup_qubole_loggers(self):
        # CAN BREAK if QDS change their name of logger.
        qds_log_lvl = self.qubole_config.qds_sdk_logging_level
        logger.info("setting QDS logger level to: {}".format(qds_log_lvl))
        logger_qds = logging.getLogger("qds_connection")
        logger_qds.setLevel(qds_log_lvl)

    def _print_partial_log(self, cmd, err_ptr, log_ptr):
        log, err_len, log_len = cmd.get_log_partial(err_ptr, log_ptr)
        logger.debug(log, err_len, log_len)
        new_log_bytes = int(err_len) + int(log_len) - log_ptr
        if int(err_len) > 0:
            err_ptr += int(err_len)
            if new_log_bytes > 0:
                log = log[-new_log_bytes]
        else:
            log_ptr += int(log_len)
            err_ptr += int(err_len)
        return log, err_ptr, log_ptr, new_log_bytes

    def _get_url(self, qubole_cmd_id):
        cmd_id = qubole_cmd_id
        host = self.qubole_config.api_url.replace("/api", "")
        return "{host}/v2/analyze?command_id={id}".format(host=host, id=cmd_id)

    def _handle_qubole_operator_execution(self, cmd):
        """
        Handles the Airflow + Databricks lifecycle logic for a Databricks operator
        :param run_id: Databricks run_id
        :param hook: Airflow databricks hook
        :param task_id: Databand Task Id.

        """
        self.qubole_cmd_id = cmd_id = cmd.id
        self.qubole_job_url = self._get_url(cmd.id)
        self.task_run.set_external_resource_urls({"qubole url": self.qubole_job_url})
        self.task_run.tracker.log_metric("qubole_cmd_id", cmd_id)

        self._qubole_banner(cmd.status)

        log_ptr, err_ptr = 0, 0

        while True:
            cmd = SparkCommand.find(cmd_id)
            status = cmd.status
            self._qubole_banner(status)

            log, err_ptr, log_ptr, received_log = self._print_partial_log(
                cmd, err_ptr, log_ptr
            )
            if received_log > 0 and self.qubole_config.show_spark_log:
                logger.info("Spark LOG:")
                logger.info(log)
            if SparkCommand.is_done(status):
                if SparkCommand.is_success(status):
                    return True
                else:  # failed
                    raise failed_to_run_qubole_job(
                        status, self.qubole_job_url, log[-15:]
                    )
            else:
                time.sleep(self.qubole_config.status_polling_interval_seconds)

    def _qubole_banner(self, status):
        b = TextBanner(
            "Spark task {} is submitted to Qubole cluster labeled: {}".format(
                self.task.task_id, self.qubole_config.cluster_label
            ),
            color="magenta",
        )
        b.column("Status", status)
        b.column("URL", self.qubole_job_url)
        logger.info(b.get_banner_str())

    def run_pyspark(self, pyspark_script):
        # should be reimplemented using SparkSubmitHook (maybe from airflow)
        # note that config jars are not supported.

        arguments = subprocess.list2cmdline(
            list_of_strings(self.task.application_args())
        )

        cmd = SparkCommand.create(
            script_location=self.deploy.sync(pyspark_script),
            language="python",
            user_program_arguments=arguments,
            arguments=subprocess.list2cmdline(self.config_to_command_line()),
            label=self.qubole_config.cluster_label,
            name=self.task.task_id,
        )
        self._handle_qubole_operator_execution(cmd)

        return True

    def get_logs(self):
        if self.qubole_cmd_id:
            return SparkCommand.get_log_id(self.qubole_cmd_id)
        return None

    # runs Java apps
    def run_spark(self, main_class):
        spark_cmd_line = CmdLineBuilder()
        spark_cmd_line.add("/usr/lib/spark/bin/spark-submit", "--class", main_class)
        spark_cmd_line.extend(self.config_to_command_line())

        # application jar
        spark_cmd_line.add(self.deploy.sync(self.config.main_jar))
        # add user side args
        spark_cmd_line.extend(list_of_strings(self.task.application_args()))

        cmd = SparkCommand.create(
            cmdline=spark_cmd_line.get_cmd_line(),
            language="command_line",
            label=self.qubole_config.cluster_label,
            name=self.task.task_id,
        )
        self._handle_qubole_operator_execution(cmd)

    def on_kill(self):
        if not self.qubole_cmd_id:
            return
        try:
            SparkCommand.cancel(self.qubole_cmd_id)
        except Exception as e:
            logger.error("Failed to stop qubole", e)