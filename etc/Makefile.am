#if HAVE_SYSTEMD
systemdsystemunit_DATA = flux-coral2-dws.service
#endif

fluxconfdir = $(sysconfdir)/flux
prologdir = $(fluxlibexecdir)/prolog.d
epilogdir = $(fluxlibexecdir)/epilog.d
housekeepingdir = $(fluxlibexecdir)/housekeeping.d

nobase_dist_fluxconf_SCRIPTS = \
	modprobe/rc1.d/coral2.py

dist_prolog_SCRIPTS = slingshot-cxi-alloc.sh
dist_epilog_SCRIPTS = slingshot-cxi-free.sh
dist_housekeeping_SCRIPTS = slingshot-cxi-cleanup.sh
