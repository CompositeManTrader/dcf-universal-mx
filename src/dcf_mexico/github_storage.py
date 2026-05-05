"""
GitHub Storage para persistencia permanente de XBRLs subidos via Streamlit.

Usa la GitHub API REST (Contents endpoint) para hacer commit + push automatico
de archivos al repo desde la app de Streamlit.

REQUIREMENTS:
1. GitHub Personal Access Token (PAT) con permiso 'contents:write'
   - Generar en: https://github.com/settings/tokens
   - Fine-grained recomendado: solo este repo, solo Contents Read+Write
2. Configurar en Streamlit secrets:

   Streamlit Cloud (app settings -> Secrets):
   ```toml
   [github]
   token  = "ghp_xxxxxxxxxxxx"
   repo   = "CompositeManTrader/dcf-universal-mx"
   branch = "main"
   ```

   Local (.streamlit/secrets.toml -- NO commitear):
   ```toml
   [github]
   token  = "ghp_xxxxxxxxxxxx"
   repo   = "CompositeManTrader/dcf-universal-mx"
   branch = "main"
   ```
"""
import base64
import json
from typing import Optional, Tuple
from dataclasses import dataclass

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


@dataclass
class GitHubConfig:
    """Config para GitHub API."""
    token: str
    repo: str            # "owner/repo"
    branch: str = "main"

    @classmethod
    def from_streamlit_secrets(cls) -> Optional["GitHubConfig"]:
        """Lee config desde st.secrets['github'] si está configurado."""
        try:
            import streamlit as st
            if "github" not in st.secrets:
                return None
            gh = st.secrets["github"]
            if "token" not in gh or "repo" not in gh:
                return None
            return cls(
                token=gh["token"],
                repo=gh["repo"],
                branch=gh.get("branch", "main"),
            )
        except Exception:
            return None


@dataclass
class CommitResult:
    """Resultado de un commit."""
    ok: bool
    message: str
    commit_url: Optional[str] = None
    file_url: Optional[str] = None
    error_detail: Optional[str] = None


def commit_file_to_github(
    filename: str,
    file_bytes: bytes,
    config: GitHubConfig,
    target_dir: str = "data/raw_xbrl",
    commit_message: Optional[str] = None,
) -> CommitResult:
    """Commit un archivo al repo GitHub via API.

    Si el archivo ya existe, lo actualiza (PUT con sha existente).
    Si no existe, lo crea.

    Args:
        filename: nombre del archivo (e.g. "ifrsxbrl_CUERVO_2025-4.xls")
        file_bytes: contenido binario del archivo
        config: GitHubConfig con token + repo + branch
        target_dir: directorio dentro del repo (default "data/raw_xbrl")
        commit_message: mensaje de commit (auto-generado si None)

    Returns:
        CommitResult con status + URLs.
    """
    if not HAS_REQUESTS:
        return CommitResult(
            ok=False, message="`requests` no está instalado",
            error_detail="pip install requests"
        )

    if not config or not config.token:
        return CommitResult(
            ok=False, message="GitHub token no configurado",
            error_detail="Configura st.secrets['github']['token'] en Streamlit"
        )

    # API endpoint
    path_in_repo = f"{target_dir}/{filename}"
    url = f"https://api.github.com/repos/{config.repo}/contents/{path_in_repo}"
    headers = {
        "Authorization": f"token {config.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 1) GET para verificar si existe (necesitamos sha para update)
    sha = None
    try:
        r_get = requests.get(url, headers=headers, params={"ref": config.branch}, timeout=15)
        if r_get.status_code == 200:
            sha = r_get.json().get("sha")
        elif r_get.status_code == 404:
            sha = None  # archivo no existe, vamos a crear
        else:
            return CommitResult(
                ok=False,
                message=f"Error GET (HTTP {r_get.status_code})",
                error_detail=r_get.text[:500],
            )
    except requests.RequestException as e:
        return CommitResult(
            ok=False, message="Error red al verificar archivo",
            error_detail=str(e),
        )

    # 2) PUT para crear o actualizar
    msg = commit_message or (
        f"feat(data): {'update' if sha else 'add'} XBRL {filename} via Streamlit"
    )

    payload = {
        "message": msg,
        "content": base64.b64encode(file_bytes).decode("utf-8"),
        "branch": config.branch,
    }
    if sha:
        payload["sha"] = sha

    try:
        r_put = requests.put(url, headers=headers, json=payload, timeout=30)
        if r_put.status_code in (200, 201):
            data = r_put.json()
            return CommitResult(
                ok=True,
                message=f"{'Actualizado' if sha else 'Creado'}: {filename}",
                commit_url=data.get("commit", {}).get("html_url"),
                file_url=data.get("content", {}).get("html_url"),
            )
        else:
            try:
                error_detail = r_put.json().get("message", r_put.text)
            except Exception:
                error_detail = r_put.text[:500]
            return CommitResult(
                ok=False,
                message=f"Error PUT (HTTP {r_put.status_code})",
                error_detail=error_detail,
            )
    except requests.RequestException as e:
        return CommitResult(
            ok=False, message="Error red al subir archivo",
            error_detail=str(e),
        )


def list_xbrls_in_github(config: GitHubConfig,
                          target_dir: str = "data/raw_xbrl") -> Tuple[bool, list]:
    """Lista los archivos en el directorio del repo.

    Returns: (ok, list of {name, sha, size, download_url})
    """
    if not HAS_REQUESTS or not config:
        return False, []

    url = f"https://api.github.com/repos/{config.repo}/contents/{target_dir}"
    headers = {
        "Authorization": f"token {config.token}",
        "Accept": "application/vnd.github+json",
    }
    try:
        r = requests.get(url, headers=headers, params={"ref": config.branch}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return True, [
                    {
                        "name": item["name"],
                        "sha": item["sha"],
                        "size_kb": item["size"] / 1024,
                        "download_url": item.get("download_url"),
                    }
                    for item in data
                    if item.get("type") == "file"
                ]
        return False, []
    except requests.RequestException:
        return False, []


def test_github_connection(config: GitHubConfig) -> Tuple[bool, str]:
    """Test si las credenciales funcionan.

    Returns: (ok, message)
    """
    if not HAS_REQUESTS:
        return False, "`requests` no instalado"
    if not config:
        return False, "Config no proporcionada"

    url = f"https://api.github.com/repos/{config.repo}"
    headers = {
        "Authorization": f"token {config.token}",
        "Accept": "application/vnd.github+json",
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return True, (
                f"OK ✓ Conectado a {data['full_name']} "
                f"(branch: {config.branch}, default: {data.get('default_branch')})"
            )
        elif r.status_code == 401:
            return False, "Token inválido o expirado (HTTP 401)"
        elif r.status_code == 404:
            return False, f"Repo {config.repo} no encontrado o sin permiso (HTTP 404)"
        else:
            return False, f"Error HTTP {r.status_code}: {r.text[:200]}"
    except requests.RequestException as e:
        return False, f"Error red: {e}"
