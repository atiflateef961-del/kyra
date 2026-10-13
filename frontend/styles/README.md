# Kyra frontend design tokens

`tokens.css` is the source of truth for Task 3's visual foundations. Import it
from the future Next.js global stylesheet. Use semantic variables such as
`--surface`, `--text`, and `--primary`; do not hardcode palette values in
components.

Set `data-theme="dark"` on the document root to enable night mode. The default
is the distinct warm light theme, not a simple inversion. The tokens also expose
focus, reduced-motion, liquid, glass, and soft-neumorphic values for later UI
tasks.
