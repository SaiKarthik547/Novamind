import os

for d in ['agents']:
  for f in os.listdir(d):
    if f.endswith('.py'):
      p = os.path.join(d, f)
      with open(p, 'r', encoding='utf-8') as fh: c = fh.read()
      orig = c
      c = c.replace("role=\\'Agent\\'", 'role="Agent"')
      if c != orig:
        with open(p, 'w', encoding='utf-8') as fh: fh.write(c)
        print('Fixed:', p)
