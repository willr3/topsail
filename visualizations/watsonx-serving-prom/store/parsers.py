import types
import pathlib
import logging
import yaml
import os
import json
import datetime

import jsonpath_ng

import matrix_benchmarking.cli_args as cli_args
import matrix_benchmarking.store.prom_db as store_prom_db

from . import prom as workload_prom


register_important_file = None # will be when importing store/__init__.py

K8S_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
SHELL_DATE_TIME_FMT = "%a %b %d %H:%M:%S %Z %Y"
ANSIBLE_LOG_DATE_TIME_FMT = "%Y-%m-%d %H:%M:%S"

artifact_dirnames = types.SimpleNamespace()
artifact_dirnames.CLUSTER_DUMP_PROM_DB_DIR = "*__cluster__dump_prometheus_dbs/*__cluster__dump_prometheus_db"
artifact_dirnames.CLUSTER_DUMP_PROM_DB_UWM_DIR = "*__cluster__dump_prometheus_dbs/*__cluster__dump_prometheus_db_uwm"

IMPORTANT_FILES = [
    f"{artifact_dirnames.CLUSTER_DUMP_PROM_DB_DIR}/prometheus.t*",
    f"{artifact_dirnames.CLUSTER_DUMP_PROM_DB_DIR}/nodes.json",

    f"{artifact_dirnames.CLUSTER_DUMP_PROM_DB_UWM_DIR}/prometheus.t*",
    f"*/test_start_end.json", f"test_start_end.json",
]

def ignore_file_not_found(fn):
    def decorator(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FileNotFoundError as e:
            logging.warning(f"{fn.__name__}: FileNotFoundError: {e}")
            return None

    return decorator


def _parse_always(results, dirname, import_settings):
    # parsed even when reloading from the cache file
    pass


def _parse_once(results, dirname):
    results.metrics = _extract_metrics(dirname)
    results.nodes_info = _parse_nodes_info(dirname) or {}
    results.cluster_info = _extract_cluster_info(results.nodes_info)
    results.tests_timestamp = _find_test_timestamps(dirname)


def _extract_metrics(dirname):
    if artifact_paths.CLUSTER_DUMP_PROM_DB_DIR is None:
        logging.error(f"Couldn't find the Prom DB directory: {dirname / artifact_dirnames.CLUSTER_DUMP_PROM_DB_DIR}")
        return

    METRICS = {
        "sutest": (str(artifact_paths.CLUSTER_DUMP_PROM_DB_DIR / "prometheus.t*"), workload_prom.get_sutest_metrics()),
        "uwm": (str(artifact_paths.CLUSTER_DUMP_PROM_DB_UWM_DIR / "prometheus.t*"), []),
    }

    metrics = {}
    for name, (tarball_glob, metric) in METRICS.items():
        try:
            prom_tarball = list(dirname.glob(tarball_glob))[0]
        except IndexError:
            logging.warning(f"No {tarball_glob} in '{dirname}'.")
            continue

        register_important_file(dirname, prom_tarball.relative_to(dirname))
        metrics[name] = store_prom_db.extract_metrics(prom_tarball, metric, dirname)

    return metrics


@ignore_file_not_found
def _parse_nodes_info(dirname, sutest_cluster=True):
    nodes_info = {}

    filename = artifact_paths.CLUSTER_DUMP_PROM_DB_DIR / "nodes.json"

    with open(register_important_file(dirname, filename)) as f:
        nodeList = json.load(f)

    for node in nodeList["items"]:
        node_name = node["metadata"]["name"]
        node_info = nodes_info[node_name] = types.SimpleNamespace()

        node_info.name = node_name
        node_info.sutest_cluster = sutest_cluster
        node_info.managed = "managed.openshift.com/customlabels" in node["metadata"]["annotations"]
        node_info.instance_type = node["metadata"]["labels"].get("node.kubernetes.io/instance-type", "N/A")

        node_info.control_plane = "node-role.kubernetes.io/control-plane" in node["metadata"]["labels"] or "node-role.kubernetes.io/master" in node["metadata"]["labels"]

        node_info.infra = \
            not node_info.control_plane

    return nodes_info


def _extract_cluster_info(nodes_info):
    cluster_info = types.SimpleNamespace()

    cluster_info.node_count = [node_info for node_info in nodes_info.values() \
                                     if node_info.sutest_cluster]

    cluster_info.control_plane = [node_info for node_info in nodes_info.values() \
                                 if node_info.sutest_cluster and node_info.control_plane]

    cluster_info.infra = [node_info for node_info in nodes_info.values() \
                                if node_info.sutest_cluster and node_info.infra]

    return cluster_info

def _find_test_timestamps(dirname):
    test_timestamps = []
    FILENAME = "test_start_end.json"
    logging.info(f"Searching for {FILENAME} ...")
    for test_timestamp_filename in sorted(dirname.glob(f"**/{FILENAME}")):

        with open(register_important_file(dirname, test_timestamp_filename.relative_to(dirname))) as f:
            try:
                data = json.load(f)
                test_timestamp = types.SimpleNamespace()
                start = data["start"][:-4]+"Z"
                test_timestamp.start = datetime.datetime.strptime(start, "%Y-%m-%dT%H:%M:%S.%f%z")
                end = data["end"]
                test_timestamp.end = datetime.datetime.strptime(end, "%Y-%m-%dT%H:%M:%S%z")
                test_timestamp.settings = data["settings"]
                if "expe" in test_timestamp.settings:
                    del test_timestamp.settings["expe"]
                if "e2e_test" in test_timestamp.settings:
                    del test_timestamp.settings["e2e_test"]
                if "model_name" in test_timestamp.settings:
                    test_timestamp.settings["*model_name"] = test_timestamp.settings["model_name"]
                    del test_timestamp.settings["model_name"]

                test_timestamps.append(test_timestamp)
            except Exception as e:
                logging.warning(f"Failed to parse {test_timestamp_filename}: {e.__class__.__name__}: {e}")

    logging.info(f"Found {len(test_timestamps)}x {FILENAME}")
    return test_timestamps
