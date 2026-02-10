nobase_fluxk8spy_PYTHON = \
	__init__.py \
	crd.py \
	directivebreakdown.py \
	operator/defaults.py
	operator/__init__.py
	operator/minicluster.py
	operator/rabbits.py
	operator/volumes.py
	watch.py \
	cleanup.py \
	workflow.py \
	storage.py \
	systemstatus.py

clean-local:
	-rm -f *.pyc */*.pyc *.pyo */*.pyo
	-rm -rf __pycache__ */__pycache__

install-data-hook:
	$(AM_V_at)echo Linking flux_k8s py in non-standard location... && \
	  $(INSTALL) -d -m 0755 "$(DESTDIR)$(fluxk8spylinkdir)" && \
	  target=$(fluxk8spydir) && \
	  f=$${target##*/} && \
	  cd "$(DESTDIR)$(fluxk8spylinkdir)" && \
	  rm -f $$f && \
	  $(LN_S) $$target .

uninstall-local:
	$(AM_V_at)target=$(fluxk8spydir) && f=$${target##*/} && \
	  echo "Removing $(fluxk8spylinkdir)/$$f" && \
	  rm -rf $(fluxk8spylinkdir)/$$f
