import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from data_imports.models import StagingAsset

class Command(BaseCommand):
    help = 'Carga el archivo Excel de inventario a la tabla temporal (Staging) excluyendo credenciales'

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="Ruta del Excel de inventario en almacenamiento privado.")

    def handle(self, *args, **kwargs):
        file_path = kwargs["archivo"]
        
        try:
            self.stdout.write("Leyendo archivo Excel...")
            xls = pd.ExcelFile(file_path)
            
            if 'Control de activos Bogotá' in xls.sheet_names:
                df_bta = pd.read_excel(xls, sheet_name='Control de activos Bogotá')
                self.process_dataframe(df_bta, 'Control de activos Bogotá', 2)
                
            if 'Control de activos STM' in xls.sheet_names:
                df_stm = pd.read_excel(xls, sheet_name='Control de activos STM', header=1)
                self.process_dataframe(df_stm, 'Control de activos STM', 3)
                
            self.stdout.write(self.style.SUCCESS("Extracción a Staging finalizada exitosamente."))
        except FileNotFoundError:
            raise CommandError("No se encontró el archivo Excel indicado.") from None
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error inesperado: {str(e)}"))

    def clean_value(self, val):
        if pd.isna(val) or str(val).strip().upper() in ['N/A', 'N/T', 'NAN', '']:
            return None
        return str(val).strip()

    def process_dataframe(self, df, sheet_name, start_row):
        df.columns = df.columns.str.strip().str.upper()
        count = 0
        
        for index, row in df.iterrows():
            elemento = self.clean_value(row.get('ELEMENTO'))
            placa = self.clean_value(row.get('ACTIVO FIJO')) or self.clean_value(row.get('PLACA FISICA'))
            
            if not elemento and not placa:
                continue 
            
            StagingAsset.objects.create(
                sheet_name=sheet_name,
                row_number=index + start_row,
                employee_name=self.clean_value(row.get('USUARIO')),
                employee_document=self.clean_value(row.get('CEDULA')),
                element=elemento,
                legacy_asset_tag=placa,
                serial_number=self.clean_value(row.get('SERIAL')),
                brand=self.clean_value(row.get('MARCA')),
                model=self.clean_value(row.get('MODELO')),
                company=self.clean_value(row.get('COMPAÑÍA')) or self.clean_value(row.get('COMPANIA')),
                site=self.clean_value(row.get('SEDE')),
                area=self.clean_value(row.get('AREA')),
                ram=self.clean_value(row.get('MEMORIA RAM')),
                storage=self.clean_value(row.get('DISCO')),
                processor=self.clean_value(row.get('PROCESADOR')),
                operating_system=self.clean_value(row.get('SISTEMA OPERATIVO')),
                hostname=self.clean_value(row.get('HOSTNAME')),
                mac_address=self.clean_value(row.get('MAC')),
                observations=self.clean_value(row.get('OBSERVACIONES'))
            )
            count += 1
            
        self.stdout.write(f"Procesados {count} registros de la hoja '{sheet_name}'.")
