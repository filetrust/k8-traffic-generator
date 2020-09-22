import os
import logging
import logging.config
from pythonjsonlogger import jsonlogger
from datetime import datetime;
import requests
import time

from kubernetes import client, config, utils
import kubernetes.client
from kubernetes.client.rest import ApiException

class ElkJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(ElkJsonFormatter, self).add_fields(log_record, record, message_dict)
        log_record['@timestamp'] = datetime.now().isoformat()
        log_record['level'] = record.levelname
        log_record['logger'] = record.name

logging.config.fileConfig('logging.conf')
logger = logging.getLogger('inspector')

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
FILE_PROCESSOR = "file-processor"

# Setup K8 configs
config.load_kube_config()
configuration = kubernetes.client.Configuration()
api_instance = kubernetes.client.BatchV1Api(kubernetes.client.ApiClient(configuration))

def kube_delete_empty_pods(namespace='default', phase='Succeeded'):
    """
    Pods are never empty, just completed the lifecycle.
    As such they can be deleted.
    Pods can be without any running container in 2 states:
    Succeeded and Failed. This call doesn't terminate Failed pods by default.
    """
    # The always needed object
    #deleteoptions = client.V1DeleteOptions()
    # We need the api entry point for pods
    api_pods = client.CoreV1Api()
    # List the pods
    try:
        pods = api_pods.list_namespaced_pod(namespace)
    except ApiException as e:
        logging.error("Exception when calling CoreV1Api->list_namespaced_pod: %s\n" % e)
        return

    for pod in pods.items:
        logging.debug(pod)
        podname = pod.metadata.name
        if not podname.startswith(FILE_PROCESSOR):
            continue 
        try:
            if pod.status.phase == phase:
                api_response = api_pods.delete_namespaced_pod(podname, namespace, body={})
                logging.info("Pod: {} deleted!".format(podname))
                logging.debug(api_response)
            else:
                logging.info("Pod: {} still not done... Phase: {}".format(podname, pod.status.phase))
        except ApiException as e:
            logging.error("Exception when calling CoreV1Api->delete_namespaced_pod: %s\n" % e)
    
    return

def kube_cleanup_finished_jobs(namespace='default', state='Finished'):
  
    """
    Since the TTL flag (ttl_seconds_after_finished) is still in alpha (Kubernetes 1.12) jobs need to be cleanup manually
    As such this method checks for existing Finished Jobs and deletes them.
    By default it only cleans Finished jobs. Failed jobs require manual intervention or a second call to this function.
    Docs: https://kubernetes.io/docs/concepts/workloads/controllers/jobs-run-to-completion/#clean-up-finished-jobs-automatically
    For deletion you need a new object type! V1DeleteOptions! But you can have it empty!
    CAUTION: Pods are not deleted at the moment. They are set to not running, but will count for your autoscaling limit, so if
             pods are not deleted, the cluster can hit the autoscaling limit even with free, idling pods.
             To delete pods, at this moment the best choice is to use the kubectl tool
             ex: kubectl delete jobs/JOBNAME.
             But! If you already deleted the job via this API call, you now need to delete the Pod using Kubectl:
             ex: kubectl delete pods/PODNAME
    """
    #deleteoptions = client.V1DeleteOptions()
    try: 
        jobs = api_instance.list_namespaced_job(namespace)
        #print(jobs)
    except ApiException as e:
        print("Exception when calling BatchV1Api->list_namespaced_job: %s\n" % e)
        return
    
    # Now we have all the jobs, lets clean up
    # We are also logging the jobs we didn't clean up because they either failed or are still running
    for job in jobs.items:
        logging.debug(job)
        jobname = job.metadata.name
        jobstatus = job.status.conditions
        if not jobname.startswith(FILE_PROCESSOR):
            continue
        if job.status.succeeded == 1:
            # Clean up Job
            logging.info("Cleaning up Job: {}. Finished at: {}".format(jobname, job.status.completion_time))
            try: 
                # What is at work here. Setting Grace Period to 0 means delete ASAP. Otherwise it defaults to
                # some value I can't find anywhere. Propagation policy makes the Garbage cleaning Async
                api_response = api_instance.delete_namespaced_job(jobname,
                                                                  namespace)
                logging.debug(api_response)
            except ApiException as e:
                print("Exception when calling BatchV1Api->delete_namespaced_job: %s\n" % e)
        else:
            if jobstatus is None and job.status.active == 1:
                jobstatus = 'active'
            logging.info("Job: {} not cleaned up. Current status: {}".format(jobname, jobstatus))
    
    # Now that we have the jobs cleaned, let's clean the pods
    kube_delete_empty_pods(namespace)
    # And we are done!
    return

def kube_processor_jobs_running(namespace='default', state='Finished'):
  
    try: 
        jobs = api_instance.list_namespaced_job(namespace)
        #print(jobs)
    except ApiException as e:
        print("Exception when calling BatchV1Api->list_namespaced_job: %s\n" % e)
        return True
    
    # Now we have all the jobs, lets clean up
    # We are also logging the jobs we didn't clean up because they either failed or are still running
    for job in jobs.items:
        logging.debug(job)
        jobname = job.metadata.name
        jobstatus = job.status.conditions
        if jobname.startswith(FILE_PROCESSOR):
            return True
    
    return False


class Main():

    @staticmethod
    def log_level(level):
        logging.basicConfig(level=getattr(logging, level))

    @staticmethod
    def run_processor():

        while kube_processor_jobs_running():
            logger.debug("Previous job still running")
            kube_cleanup_finished_jobs()
            time.sleep(1)

        job_name = FILE_PROCESSOR

        envs = [client.V1EnvVar(name="API_TOKEN", value=os.getenv("API_TOKEN")),
                client.V1EnvVar(name="FILE_TO_PROCESS", value=os.getenv("FILE_TO_PROCESS", "Reports 2.pdf"))
               ]

        processor_container = client.V1Container(
            name="processor",
            image=os.getenv("PROCESSOR_IMAGE", "ggrig/k8-traffic:re_processor"),
            env=envs)

        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            containers=[processor_container])

        # Create and configure a spec section
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(name=job_name, labels={
                                        "app": "file-rebuild-processor"}),
            spec=pod_spec)

        # Create the specification of the job
        spec = client.V1JobSpec(
            template=template,
            backoff_limit=0)

        # Instantiate the job object
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(name=job_name),
            spec=spec)

        logger.info("trying to create a job:" + job_name)
        client.BatchV1Api().create_namespaced_job(
            body=job,
            namespace="default")

    @staticmethod
    def application():

        # No Loop debug run
        Main.run_processor()
        return
     
        while True:
            try:
                Main.run_processor()
            except Exception as e:
                logger.error(e)

    @staticmethod
    def main():
        Main.log_level(LOG_LEVEL)
        Main.application()

if __name__ == "__main__":
    Main.main()
