import urllib.request
import re

req = urllib.request.Request("http://192.168.1.17:3005/")
with urllib.request.urlopen(req) as r:
    html = r.read().decode("utf-8")
    print("HTML LEN:", len(html))
    print("CONTAINS Memeriksa sesi CBT:", "Memeriksa sesi CBT" in html)
    scripts = re.findall(r'<script[^>]*src=[\'"]([^\'"]+)[\'"]', html)
    print("SCRIPTS FOUND:", len(scripts))
    for s in scripts:
        print(" -", s)
