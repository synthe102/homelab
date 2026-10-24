"""Render the actual receiver template with amtool (the same version as Mimir).

Run from the repository root:
  nix shell nixpkgs#prometheus-alertmanager nixpkgs#python3Packages.pyyaml \
    -c python3 -m unittest discover \
    -s clusters/k8s-01/apps/monitoring/kube-prometheus-stack/tests -v
"""

from datetime import datetime, timedelta
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import parse_qs, quote_plus, urlparse

import yaml


class MessageHTML(HTMLParser):
    def __init__(self, message):
        super().__init__()
        self.stack = []
        self.links = {}
        self.link = None
        self.feed(message)
        self.close()
        assert not self.stack, self.stack

    def handle_starttag(self, tag, attrs):
        assert tag in {"b", "code", "pre", "a"}, tag
        self.stack.append(tag)
        if tag == "a":
            self.link = dict(attrs)["href"]
            assert urlparse(self.link).scheme in {"http", "https"}

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag
        if tag == "a":
            self.link = None

    def handle_data(self, data):
        if self.link:
            self.links.setdefault(data, []).append(self.link)


class TelegramTemplateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.amtool = os.environ.get("AMTOOL") or shutil.which("amtool")
        if not cls.amtool:
            raise RuntimeError("amtool is required; see the command in this file's docstring")
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.folder = Path(cls.temp.name)
        config_path = Path(__file__).resolve().parents[1] / "configs/alertmanagerconfig.yaml"
        # BaseLoader accepts the CRD's unquoted '=' matcher and preserves the template.
        config = yaml.load(config_path.read_text(), Loader=yaml.BaseLoader)
        receiver = next(r for r in config["spec"]["receivers"] if r["name"] == "telegram")
        message = receiver["telegramConfigs"][0]["message"]
        cls.template = cls.folder / "telegram.tmpl"
        cls.template.write_text('{{ define "telegram" }}' + message + "{{ end }}")

    def alert(self, **changes):
        alert = {
            "status": "firing",
            "labels": {
                "alertname": "BrokerNotReady",
                "severity": "critical",
                "k8s_cluster_name": "k8s-01",
                "namespace": "monitoring",
                "pod": "mimir-mixed-0",
            },
            "annotations": {"summary": "Kafka broker is not ready", "description": "Broker has been unready for five minutes."},
            "startsAt": "2026-10-24T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": '/graph?g0.expr=up%7Bjob%3D%22kafka%22%7D+%3D%3D+0&g0.tab=1',
        }
        for key, value in changes.items():
            if key in {"labels", "annotations"}:
                alert[key].update(value)
            else:
                alert[key] = value
        return alert

    def render(self, *alerts):
        data = {
            "receiver": "telegram",
            "status": "firing" if any(a["status"] == "firing" for a in alerts) else "resolved",
            "alerts": alerts,
            "commonLabels": {"alertname": "BrokerNotReady", "severity": "critical"},
            "commonAnnotations": {},
        }
        fixture = self.folder / "data.json"
        fixture.write_text(json.dumps(data))
        result = subprocess.run(
            [self.amtool, "template", "render", "--template.glob=" + str(self.template),
             '--template.text={{ template "telegram" . }}', "--template.type=html", "--template.data=" + str(fixture)],
            capture_output=True, text=True, check=True,
        )
        message = result.stdout.strip()
        self.assertLessEqual(len(message), 4096)
        self.assertNotIn("<no value>", message)
        return message, MessageHTML(message).links

    def pane(self, link):
        params = parse_qs(urlparse(link).query)
        self.assertEqual(params["schemaVersion"], ["1"])
        return json.loads(params["panes"][0])["A"]

    def test_query_and_pod_metadata_links(self):
        message, links = self.render(self.alert())
        self.assertIn("1 firing · 0 resolved", message)
        self.assertIn("Pod: <code>mimir-mixed-0</code>", message)
        self.assertIn("Active for", message)
        query = self.pane(links["View failing query"][0])
        self.assertEqual(query["datasource"], "prometheus")
        self.assertEqual(query["queries"][0]["expr"], 'up{job="kafka"} == 0')
        logs = self.pane(links["Logs"][0])
        self.assertEqual(logs["datasource"], "loki")
        self.assertEqual(logs["queries"][0]["expr"], '{namespace="monitoring"} | pod="mimir-mixed-0"')
        self.assertEqual(query["range"], logs["range"])
        self.assertNotIn("Alerting</a>", message)

    def test_grouped_resources_and_mixed_statuses(self):
        resolved = self.alert(status="resolved", labels={"pod": "broker-resolved"},
                              annotations={"description": "This broker recovered."}, endsAt="2026-10-24T10:25:00Z")
        firing = self.alert(labels={"pod": "broker-firing"}, annotations={"description": "This broker is still failing."})
        message, links = self.render(resolved, firing)
        self.assertIn("1 firing · 1 resolved", message)
        self.assertLess(message.index("broker-firing"), message.index("broker-resolved"))
        self.assertIn("This broker recovered.", message)
        self.assertIn("This broker is still failing.", message)
        expressions = [self.pane(link)["queries"][0]["expr"] for link in links["Logs"]]
        self.assertEqual(expressions, ['{namespace="monitoring"} | pod="broker-firing"',
                                       '{namespace="monitoring"} | pod="broker-resolved"'])

    def test_resolved_timestamp_duration_and_incident_window(self):
        message, links = self.render(self.alert(status="resolved", endsAt="2026-10-24T10:25:00Z"))
        self.assertIn("✅ <b>CRITICAL · RESOLVED</b>", message)
        self.assertIn("Started: 24 Oct 2026 12:00:00 CEST", message)
        self.assertIn("Resolved: 24 Oct 2026 12:25:00 CEST · Duration: 25m 0s", message)
        self.assertNotIn("Active for", message)
        start = datetime.fromisoformat("2026-10-24T09:45:00+00:00")
        for name in ("View failing query", "Logs"):
            window = self.pane(links[name][0])["range"]
            self.assertEqual(int(window["from"]), int(start.timestamp() * 1000))
            self.assertEqual(int(window["to"]), int((start + timedelta(minutes=55)).timestamp() * 1000))

    def test_daylight_saving_transition(self):
        message, _ = self.render(self.alert(status="resolved", startsAt="2026-10-25T00:30:00Z", endsAt="2026-10-25T01:30:00Z"))
        self.assertIn("Started: 25 Oct 2026 02:30:00 CEST", message)
        self.assertIn("Resolved: 25 Oct 2026 02:30:00 CET · Duration: 1h 0m 0s", message)

    def test_resolution_without_start_and_firing_timeout(self):
        message, _ = self.render(self.alert(status="resolved", startsAt="0001-01-01T00:00:00Z", endsAt="2026-10-24T10:25:00Z"))
        self.assertIn("Resolved: 24 Oct 2026 12:25:00 CEST", message)
        self.assertNotIn("Duration:", message)
        message, links = self.render(self.alert(endsAt="2099-01-01T00:00:00Z"))
        self.assertNotIn("Resolved:", message)
        link_end = int(self.pane(links["Logs"][0])["range"]["to"])
        self.assertLess(abs(link_end - datetime.now().timestamp() * 1000), 16 * 60 * 1000)

    def test_node_pvc_and_workload_details(self):
        alert = self.alert(labels={"cluster": "rook-ceph", "node": "ms01-01", "persistentvolumeclaim": "data-kafka", "statefulset": "kafka"})
        alert["labels"].pop("pod")
        message, links = self.render(alert)
        self.assertIn("Cluster: <code>k8s-01</code>", message)
        self.assertIn("Node: <code>ms01-01</code>", message)
        self.assertIn("PVC: <code>data-kafka</code>", message)
        self.assertIn("Statefulset: <code>kafka</code>", message)
        self.assertEqual(self.pane(links["Logs"][0])["queries"][0]["expr"], '{hostname="ms01-01"}')

    def test_annotation_overrides_and_ceph_documentation(self):
        annotations = {key: "https://example.com/" + key for key in ("query_url", "logs_url", "documentation", "panel_url", "dashboard_url")}
        _, links = self.render(self.alert(annotations=annotations))
        for label, key in (("View failing query", "query_url"), ("Logs", "logs_url"), ("Runbook", "documentation"),
                           ("Panel", "panel_url"), ("Dashboard", "dashboard_url")):
            self.assertEqual(links[label], [annotations[key]])

    def test_custom_logql_preserves_error_filter(self):
        expression = '{namespace="monitoring"} | pod="mimir-mixed-0" |= "disk error"'
        _, links = self.render(self.alert(annotations={"logql": expression}))
        self.assertEqual(self.pane(links["Logs"][0])["queries"][0]["expr"], expression)

    def test_falco_links_include_detection_and_resource(self):
        _, links = self.render(self.alert(labels={"source": "syscall", "rule": "Terminal shell in container", "hostname": "ms01-01"}))
        self.assertEqual(self.pane(links["Logs"][0])["queries"][0]["expr"],
                         '{source="syscall",rule="Terminal shell in container"} | hostname="ms01-01" | k8s_ns_name="monitoring" | k8s_pod_name="mimir-mixed-0"')

    def test_aliases_and_no_guessed_instance_log_selector(self):
        for pod_label in ("kubernetes_pod_name", "k8s_pod_name"):
            with self.subTest(pod_label=pod_label):
                alert = self.alert()
                alert["labels"].pop("pod")
                alert["labels"][pod_label] = "alias-pod"
                _, links = self.render(alert)
                self.assertIn('pod="alias-pod"', self.pane(links["Logs"][0])["queries"][0]["expr"])
        alert = self.alert(labels={"instance": "10.0.0.1:9100"})
        alert["labels"].pop("pod")
        _, links = self.render(alert)
        self.assertNotIn("Logs", links)

    def test_escaping_round_trips_through_html_json_url_and_logql(self):
        value = 'name"\\\n<&é'
        expression = 'metric{label="a+b & <é>"} / 100 > 0'
        _, links = self.render(self.alert(labels={"namespace": value, "pod": value},
                                          annotations={"summary": '<a href="bad">injected</a>', "error": "<script>bad</script>"},
                                          generatorURL="/graph?g0.expr=" + quote_plus(expression) + "&g0.tab=1"))
        self.assertEqual(self.pane(links["View failing query"][0])["queries"][0]["expr"], expression)
        logql = self.pane(links["Logs"][0])["queries"][0]["expr"]
        self.assertIn('name\\"\\\\\\n<&é', logql)

    def test_invalid_links_and_malformed_generator_do_not_break_message(self):
        message, links = self.render(self.alert(generatorURL="/graph?g0.expr=%ZZ", annotations={"query_url": "javascript:bad", "logs_url": "javascript:bad"}))
        self.assertNotIn("View failing query", links)
        self.assertIn("Logs", links)
        self.assertNotIn("javascript:", message)
        _, links = self.render(self.alert(generatorURL="https://example.com/rule/1"))
        self.assertEqual(links["View source"], ["https://example.com/rule/1"])

    def test_large_groups_and_long_queries_preserve_valid_html(self):
        alerts = [self.alert(labels={"pod": f"broker-{i}"}, annotations={"description": "<long & text>" * 100}) for i in range(40)]
        message, _ = self.render(*alerts)
        self.assertIn("40 firing · 0 resolved", message)
        self.assertIn("more resources omitted to fit Telegram", message)
        message, links = self.render(self.alert(generatorURL="/graph?g0.expr=" + "metric_" * 1000))
        self.assertIn("Pod: <code>mimir-mixed-0</code>", message)
        self.assertNotIn("View failing query", links)
        self.assertIn("Logs", links)

    def test_empty_group_and_missing_annotations(self):
        self.render()
        alert = self.alert(startsAt="0001-01-01T00:00:00Z", generatorURL="")
        alert["annotations"] = {}
        alert["labels"] = {"alertname": "Unknown"}
        message, links = self.render(alert)
        self.assertIn("Unknown", message)
        self.assertNotIn("Started:", message)
        self.assertEqual(links, {})


if __name__ == "__main__":
    unittest.main()
