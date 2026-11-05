import os, re
path = "src/employees/models.py"
if not os.path.exists(path):
    for root, dirs, files in os.walk('src'):
        if 'employees' in root and 'models.py' in files:
            path = os.path.join(root, 'models.py')
            break

with open(path, "r") as f:
    content = f.read()

if "acta_desvinculacion" not in content:
    content = re.sub(
        r"(class Employee\(.*?\):)",
        r"\1\n    acta_desvinculacion = models.FileField(upload_to='actas_retiro/', null=True, blank=True, verbose_name='Acta de Retiro (GI-FR-05)')",
        content, count=1
    )
    with open(path, "w") as f:
        f.write(content)
    print("Campo 'acta_desvinculacion' inyectado en Employee.")
else:
    print("El campo ya existe.")
