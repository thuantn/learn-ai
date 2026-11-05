# Third-party files

Served from `web/static/`, unmodified.

| File | Project | License |
|------|---------|---------|
| `vendor/marked.min.js` | marked 12.0.2 | MIT |
| `vendor/purify.min.js` | DOMPurify 3.1.6 | Apache-2.0 or MPL-2.0 |
| `vendor/tex-svg.min.js` | MathJax 3.2.2 | Apache-2.0 |
| `fonts/BeVietnamPro-*` | Be Vietnam Pro | SIL OFL 1.1 |
| `fonts/SpaceGrotesk-*` | Space Grotesk | SIL OFL 1.1 |

## Python packages

Installed from `requirements.txt`, not kept in this repo. All use permissive licenses except `mutagen` (GPL-2.0-or-later), which the server uses to read audio files. The Docker image includes it, so anyone distributing a built image must also meet the GPL's terms.
