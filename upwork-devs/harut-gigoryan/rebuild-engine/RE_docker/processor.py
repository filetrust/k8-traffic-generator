import os
import logging
import logging.config
from pythonjsonlogger import jsonlogger
from datetime import datetime;
import boto3
import requests
import time
from botocore.client import Config
from botocore.exceptions import ClientError

class ElkJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(ElkJsonFormatter, self).add_fields(log_record, record, message_dict)
#        log_record['@timestamp'] = datetime.now().isoformat()
        log_record['level'] = record.levelname
        log_record['logger'] = record.name

logging.config.fileConfig('logging.conf')
logger = logging.getLogger('file processor')

file_path = '/input/'
rebuild_path = '/output/'

SRC_URL = os.getenv('SOURCE_MINIO_URL', 'http://192.168.99.123:32368')
SRC_ACCESS_KEY = os.getenv('SOURCE_MINIO_ACCESS_KEY', 'test')
SRC_SECRET_KEY = os.getenv('SOURCE_MINIO_SECRET_KEY', 'test@123')
SRC_BUCKET = os.getenv('SOURCE_MINIO_BUCKET', 'input')

TGT_URL = os.getenv('TARGET_MINIO_URL', 'http://192.168.99.123:30493')
TGT_ACCESS_KEY = os.getenv('TARGET_MINIO_ACCESS_KEY', 'test')
TGT_SECRET_KEY = os.getenv('TARGET_MINIO_SECRET_KEY', 'test@123')
TGT_BUCKET = os.getenv('TARGET_MINIO_BUCKET', 'output')

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

jwt_token = os.getenv("API_TOKEN","YOUR_REBUILD_API_TOKEN")
url = os.getenv("API_URL","https://gzlhbtpvk2.execute-api.eu-west-1.amazonaws.com/Prod/api/rebuild/file")

FILE_TO_PROCESS = os.getenv("FILE_TO_PROCESS", "Reports 1.pdf")

SHELL_ACCESS = False

class Main():

    @staticmethod
    def log_level(level):
        logging.basicConfig(level=getattr(logging, level))

    @staticmethod
    def download_from_minio():

        try:
            s3 = boto3.resource('s3', endpoint_url=SRC_URL, aws_access_key_id=SRC_ACCESS_KEY,
                                aws_secret_access_key=SRC_SECRET_KEY, config=Config(signature_version='s3v4'))
            logger.debug('Check if the Bucket {} exists'.format(SRC_BUCKET))
            if (s3.Bucket(SRC_BUCKET) in s3.buckets.all()) == False:
                logger.info('Bucket {} not found.'.format(SRC_BUCKET))
                return
            bucket = s3.Bucket(SRC_BUCKET)

            #for file in bucket.objects.all():
            for file in bucket.objects.filter(Prefix=FILE_TO_PROCESS):
                path, filename = os.path.split(file.key)
                obj_file = file_path + filename
                logger.info('Downloading file {}.'.format(filename))
                bucket.download_file(file.key, obj_file)
                Main.rebuild_it(file_path, filename)
                Main.upload_to_minio(rebuild_path, filename)
                file.delete()
                # we only are intrested in processing the first file if it exists
                break

        except ClientError as e:
            logger.error("Cannot Connect to the Minio {}. Please Verify your credentials.".format(URL))
        except Exception as e:
            logger.error(e)

    @staticmethod
    def rebuild_it(file_path, filename):
        try:
            logger.info('Rebuilding file {}.'.format(filename))

            local_filename = file_path + filename
            # Send a file to Glasswall's Rebuild API
            with open(local_filename, "rb") as f:
                response = requests.post(
                    url=url,
                    files=[("file", f)],
                    headers={
                        "Authorization": jwt_token,
                        "accept": "application/octet-stream"
                    }
                )

            output_file_path = rebuild_path + filename

            if response.status_code == 200 and response.content:
                # Glasswall has now sanitised and returned this file
                # Write the sanitised file to output file path
                logger.info("The file has been successfully rebuild")
                with open(output_file_path, "wb") as f:
                    f.write(response.content)
            else:
                # An error occurred, raise it
                logger.error("Rebuild Failed: {}", format(response.raise_for_status()))

        except Exception as e:
            logger.error("Rebuild Failed with Exception")
            logger.error(e)

    @staticmethod
    def upload_to_minio(file_path, filename):

        try:
            logger.info('Uploading file {}.'.format(filename))

            s3 = boto3.resource('s3', endpoint_url=TGT_URL, aws_access_key_id=TGT_ACCESS_KEY,
                                aws_secret_access_key=TGT_SECRET_KEY, config=Config(signature_version='s3v4'))
            logger.debug('Checking if the Bucket to upload files exists or not.')
            if (s3.Bucket(TGT_BUCKET) in s3.buckets.all()) == False:
                logger.info('Bucket not Found. Creating Bucket.')
                s3.create_bucket(Bucket=TGT_BUCKET)
            logger.debug('Uploading file to bucket {} minio {}'.format(TGT_BUCKET, TGT_URL))
            file_to_upload = file_path + filename
            s3.Bucket(TGT_BUCKET).upload_file(file_to_upload, filename)
        except ClientError as e:
            logger.error("Cannot connect to the minio {}. Please vefify the Credentials.".format(TGT_URL))
        except Exception as e:
            logger.info(e)

    @staticmethod
    def application():
        endpoint = '/minio/health/ready'
        logger.debug('Checking if the Target Minio {} is avaliable.'.format(TGT_URL))
        URL = TGT_URL + endpoint
        try:
            response = requests.get(URL, timeout=2)
            if response.status_code == 200:
                logger.debug('Recieved Response code {} from {}'.format(response.status_code, URL))
            else:
                logger.error('Could Not connect to Target Minio {}.'.format(URL))
                exit(1)
        except:
            logger.error(
                'Could not connect to Target Minio {}.'.format(URL))

        URL = SRC_URL + endpoint
        logger.debug('Checking if the Source Minio {} is avaliable.'.format(SRC_URL))
        try:
            response2 = requests.get(URL, timeout=2)
            if response2.status_code == 200:
                logger.debug('Recieved status code {} from Minio {}.'.format(response2.status_code, URL))
                Main.download_from_minio()

            else:
                logger.error('Could not connect to the Soruce Minio {}.'.format(URL))
                exit(2)
        except:
            logger.error('Could not connect to Minio {}'.format(URL))

    @staticmethod
    def main():
        Main.log_level(LOG_LEVEL)
        #time.sleep(5)
        if os.name == 'nt':
            file_path = 'C:/files/'
            rebuild_path = 'C:/rebuild/'
        else:
            os.system('service filebeat start')
        Main.application()
        # let filebeat do his job
        time.sleep(2)

        #if SHELL_ACCESS:
        #    while True:
        #        time.sleep(5)


if __name__ == "__main__":
    Main.main()
