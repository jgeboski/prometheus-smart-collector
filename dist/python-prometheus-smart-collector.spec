%global shortname prometheus-smart-collector

Name:           python-%{shortname}
Version:        0.0.1
Release:        1%{?dist}
Summary:        Prometheus collector for SMART metrics

License:        MIT
URL:            https://github.com/jgeboski/%{shortname}
Source:         %{url}/archive/v%{version}/%{shortname}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  systemd-rpm-macros

Requires:       golang-github-prometheus-node-exporter
Requires:       python3-aiofiles
Requires:       python3-click
Requires:       smartmontools

%global _description %{expand:
Prometheus collector for SMART metrics.}

%description %_description

%package -n python3-%{shortname}
Summary:        %{summary}

%description -n python3-%{shortname} %_description

%prep
%autosetup -p1 -n %{shortname}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files prometheus_smart_collector

mkdir -p %{buildroot}%{_sbindir}
mv %{buildroot}%{_bindir}/%{shortname} %{buildroot}%{_sbindir}/%{shortname}
rmdir %{buildroot}%{_bindir}

install -Dpm 0644 systemd/%{shortname}.service %{buildroot}%{_unitdir}/%{shortname}.service
install -Dpm 0644 systemd/%{shortname}.timer %{buildroot}%{_unitdir}/%{shortname}.timer

%files -n python3-%{shortname} -f %{pyproject_files}
%doc README.md
%{_sbindir}/%{shortname}
%{_unitdir}/%{shortname}.service
%{_unitdir}/%{shortname}.timer

%changelog
%autochangelog
