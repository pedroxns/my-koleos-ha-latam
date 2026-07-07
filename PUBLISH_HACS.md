# Publicar My Koleos LATAM no GitHub / HACS

Este pacote já está no formato esperado para HACS:

```text
custom_components/my_koleos/
hacs.json
README.md
```

Antes do primeiro commit, edite `custom_components/my_koleos/manifest.json` e troque/adicione:

```json
"documentation": "https://github.com/SEU_USUARIO/my-koleos-ha",
"issue_tracker": "https://github.com/SEU_USUARIO/my-koleos-ha/issues",
"codeowners": ["@SEU_USUARIO"]
```

Sugestão de nome do repositório: `my-koleos-ha`.

## Comandos rápidos

```powershell
git init
git add .
git commit -m "Initial HACS release v0.3.4 com_ac_final"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/my-koleos-ha.git
git push -u origin main
git tag v0.3.4
git push origin v0.3.4
```

Depois crie uma **GitHub Release** para a tag `v0.3.4`.

Se tiver GitHub CLI:

```powershell
gh release create v0.3.4 --title "v0.3.4 com_ac_final" --notes "Primeira versão HACS com AC remoto validado via RCE_2."
```

## Teste via HACS

No Home Assistant:

1. HACS
2. Menu de três pontos
3. Custom repositories
4. URL do repositório
5. Categoria: Integration
6. ADD
```
