# Prometheus SMART Collector

A collector wrapped around `smartctl` for exporting SMART metrics to
Prometheus. The output of this collector is consumed by the Node
Exporter's `textfile` collector. No exporting functionality is provided
by this collector, the Node Exporter must be used.

Administrative permissions (root or admin capabilities) are required for
`smartctl` to query basic metrics. The benefit of the approach of this
collector is the exporter, which takes requests from clients, does not
need to run with administrative permissions. Only a small Python script
for the collector needs to run with these permissions. The Node Exporter
can continue to run as an unprivileged user, reading the file written by
the collector.

## Installing on Fedora

A Copr repo is provided for Fedora:

```
$ dnf copr enable jgeboski/prometheus-smart-collector
```
