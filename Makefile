.PHONY: help up down restart ps logs bootstrap encrypt-secrets decrypt-secrets edit-secrets pull install-backup

help:
	@echo ""
	@echo "  make bootstrap           Install Docker, age, sops (run once as sudo)"
	@echo "  make up [s=<service>]    Start all services (or one)"
	@echo "  make down [s=<service>]  Stop all services (or one)"
	@echo "  make restart [s=<svc>]   Restart all services (or one)"
	@echo "  make pull                Pull latest images"
	@echo "  make ps                  Show container status"
	@echo "  make logs s=<service>    Follow logs (e.g. make logs s=plex)"
	@echo "  make install-backup      Install/enable nightly NVMe->ZFS backup (runs once + restore test)"
	@echo "  make decrypt-secrets     Decrypt *.enc -> plaintext (needed after clone/restore)"
	@echo "  make encrypt-secrets     Encrypt plaintext secrets -> *.enc (before committing)"
	@echo "  make edit-secrets f=<f>  Edit an encrypted file in-place (e.g. make edit-secrets f=secrets/grafana.env.enc)"
	@echo ""

bootstrap:
	sudo bash bootstrap.sh

install-backup:
	sudo bash host/nvme-backup/install-nvme-backup.sh

up:
	docker compose up -d $(s)

down:
	docker compose down $(s)

restart:
	docker compose restart $(s)

pull:
	docker compose pull

ps:
	docker compose ps

logs:
	docker compose logs -f $(s)

decrypt-secrets:
	@if grep -q "REPLACE_WITH_YOUR_PUBLIC_KEY" .sops.yaml; then \
		echo "ERROR: .sops.yaml still contains the placeholder key."; \
		echo "  Generate an age key: age-keygen -o ~/.config/sops/age/keys.txt"; \
		echo "  Then paste the public key into .sops.yaml"; \
		exit 1; \
	fi
	@if ! ls secrets/*.enc 1>/dev/null 2>&1; then echo "No encrypted secrets found."; exit 0; fi
	@for f in secrets/*.enc; do \
		out="$${f%.enc}"; \
		sops --decrypt "$$f" > "$$out"; \
		echo "  $$f -> $$out"; \
	done
	@echo "Done. Plaintext files are gitignored."

encrypt-secrets:
	@if grep -q "REPLACE_WITH_YOUR_PUBLIC_KEY" .sops.yaml; then \
		echo "ERROR: .sops.yaml still contains the placeholder key."; \
		echo "  Generate an age key: age-keygen -o ~/.config/sops/age/keys.txt"; \
		echo "  Then paste the public key into .sops.yaml"; \
		exit 1; \
	fi
	@for f in $$(find secrets -maxdepth 1 \( -name "*.env" -o -name "*.yml" \) ! -name "*.example"); do \
		sops --encrypt "$$f" > "$$f.enc"; \
		echo "  $$f -> $$f.enc"; \
	done
	@echo "Done. Commit the .enc files."

edit-secrets:
	sops $(f)
