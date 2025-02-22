import boto3
import json
import io
from PIL import Image

# S3 Default Bucket
DEFAULT_BUCKET_NAME = "receipt-image-uploads"  # Replace with your S3 bucket name

class DocumentProcessor:
    def __init__(self, file_name, bucket_name=DEFAULT_BUCKET_NAME, aws_region='us-east-1'):
        """
        Initialize the DocumentProcessor object.
        """
        self.s3_client = boto3.client('s3', region_name=aws_region)
        self.textract_client = boto3.client('textract', region_name=aws_region)
        self.bucket_name = bucket_name
        self.file_name = file_name
        self.response = None
        self.tables = []

    def upload_to_s3(self, file):
        """
        Downsize and upload a document to the specified S3 bucket.
        """
        compressed_file = compress_image(file)
        self.file_name = self.file_name.rsplit('.', 1)[0] + '.jpg'
        try:
            self.s3_client.upload_fileobj(compressed_file, self.bucket_name, self.file_name)
            print(f"File '{self.file_name}' uploaded to bucket '{self.bucket_name}'.")
        except Exception as e:
            print(f"Error uploading file: {e}")

    def textract_process(self):
        print(f"Processing image '{self.file_name}' in bucket '{self.bucket_name}'...\n")
        try:
            response = self.textract_client.analyze_document(
                Document={
                    'S3Object': {
                        'Bucket': self.bucket_name,
                        'Name': self.file_name
                    }
                },
                FeatureTypes=['TABLES']
            )
            
            self.response = response
            return True

        except Exception as e:
            print(f"Error processing Textract: {e}")
            return False

    def extract_and_fix_tables(self):
        """
        Extracts table content from Textract response, combining columns and fixing hanging values.
        """
        block_map = {block['Id']: block for block in self.response['Blocks']}
        tables = []

        # Iterate through TABLE blocks
        for table_block in self.response['Blocks']:
            if table_block['BlockType'] == 'TABLE':
                table_cells = {}
                # Only process CELL blocks related to this TABLE
                for relationship in table_block.get('Relationships', []):
                    if relationship['Type'] == 'CHILD':
                        for child_id in relationship['Ids']:
                            cell_block = block_map[child_id]
                            if cell_block['BlockType'] == 'CELL':
                                row = cell_block['RowIndex']
                                col = cell_block['ColumnIndex']
                                cell_text = get_text_from_block(cell_block, block_map)

                                if row not in table_cells:
                                    table_cells[row] = {}
                                table_cells[row][col] = cell_text

                # Process the table cells
                tables.append(process_table_rows(table_cells))
        
        self.tables = tables

    def print_response(self):
        print(json.dumps(self.response, indent=4))

    def print_tables(self):
        """
        Prints the tables in a readable format.
        """
        for table_idx, table in enumerate(self.tables, 1):
            print(f"\nTable {table_idx}:")
            print("| {:<50} | {:<10} |".format("Item", "Price"))
            print("|" + "-"*52 + "|" + "-"*12 + "|")
            for row in table:
                print("| {:<50} | {:<10} |".format(row[0], row[1]))

    def generate_presigned_url(self, expiration=3600):
        """
        Generate a pre-signed URL for the S3 object that expires after a set time (default 1 hour).
        """
        try:
            jpg_name = self.file_name.rsplit('.', 1)[0] + '.jpg' # little ugly but we convert to jpeg during compression
            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': jpg_name},
                ExpiresIn=expiration
            )
            return presigned_url
        except Exception as e:
            print(f"Error generating pre-signed URL: {e}")
            return None

def get_text_from_block(cell_block, block_map):
    """
    Extracts text from a CELL block by traversing CHILD relationships.
    """
    text = []
    for relationship in cell_block.get('Relationships', []):
        if relationship['Type'] == 'CHILD':
            for child_id in relationship['Ids']:
                word_block = block_map.get(child_id, {})
                if 'Text' in word_block:
                    text.append(word_block['Text'])
    return " ".join(text).strip()

def process_table_rows(table_cells):
    """
    Combines table rows into key-value pairs (all columns except last -> key, last column -> value).
    Fixes hanging values where necessary.
    """
    processed_rows = []
    previous_row = None

    for row_index in sorted(table_cells.keys()):
        row = table_cells[row_index]
        sorted_columns = sorted(row.items())
        if len(sorted_columns) > 1:
            # Combine all columns except the last as the key
            key = " ".join([col[1] for col in sorted_columns[:-1]]).strip()
            value = sorted_columns[-1][1].strip()
        else:
            # Handle rows with just one column (possible hanging value)
            key = ""
            value = sorted_columns[0][1].strip()
        
        if key:  # Normal row
            processed_rows.append([key, value])
            previous_row = [key, value]
        elif previous_row:  # Fix hanging value
            previous_row[-1] = value
            processed_rows[-1] = previous_row

    return processed_rows

def compress_image(file, max_size_mb=5):
    image = Image.open(file)
    if image.mode != "RGB":
        print(f"Converting image mode from {image.mode} to RGB")
        image = image.convert("RGB")

    output = io.BytesIO()
    output.seek(0)
    image.save(output, format="JPEG", quality=100, optimize=True)

    target_size = max_size_mb * 1024 * 1024  # Convert max size to bytes
    quality = 95  # Start with high quality
    size_in_bytes = len(output.getvalue())

    while size_in_bytes > target_size:
        output.seek(0)  # Reset buffer pointer
        image.save(output, format="JPEG", quality=quality, optimize=True)
        size_in_bytes = len(output.getvalue())

        if quality <= 10:
            break  # Stop if quality gets too low

        quality -= 5  # Gradually reduce quality to achieve target size
    
    output.seek(0)
    return output

