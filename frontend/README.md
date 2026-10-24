# t2 Connect frontend

The single source for the frontend is `src/t2_bots/connect/static/`. The same
HTML/CSS/JavaScript is packaged with the companion and published to Vercel.
No Node dependencies, client framework or frontend build step is required.

Run `t2-connect` after `python -m pip install -e ".[gateway]"`, or use the root
Windows launcher. The workspace runs at http://127.0.0.1:4840/.

See [the frontend and deployment guide](../docs/FRONTEND.md) for the directory,
real hardware setup, release packaging and hosting.
