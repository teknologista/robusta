from robusta.api import *
import hikaru.model
import kubernetes.client.exceptions

supported_resources = ["Deployment", "DaemonSet", "ReplicaSet", "Pod", "StatefulSet"]


def to_pod_row(pod: Pod, cluster_name: str) -> List:
    resource_requests = pod_requests(pod)
    resource_limits = pod_limits(pod)
    addresses = ",".join([address.ip for address in pod.status.podIPs])
    return [
        pod.metadata.name,
        pod.metadata.namespace,
        cluster_name,
        pod.spec.nodeName,
        resource_limits.cpu,
        resource_requests.cpu,
        resource_limits.memory,
        resource_requests.memory,
        pod.metadata.creationTimestamp,
        pod_restarts(pod),
        addresses,
        len(pod.spec.containers),
        pod.status.phase,
    ]


@action
def related_pods(event: KubernetesResourceEvent):
    """
    Return the list of pods related to that k8s resource.
    For example, return all pods of a given k8s Deployment

    Supports Deployments, ReplicaSets, DaemonSets, StatefulSets and Pods
    """
    resource = event.get_resource()
    if resource.kind not in supported_resources:
        logging.error(f"Related pods is not supported for resource {resource.kind}")
        return

    if resource.kind == "Pod":
        pods = [resource]
    else:
        selector = build_selector_query(resource.spec.selector)
        pods = PodList.listNamespacedPod(
            namespace=resource.metadata.namespace, label_selector=selector
        ).obj.items

    rows = [to_pod_row(pod, event.get_context().cluster_name) for pod in pods]

    event.add_enrichment(
        [
            TableBlock(
                table_name="related pods",
                headers=[
                    "name",
                    "namespace",
                    "cluster",
                    "node",
                    "cpu limit",
                    "cpu request",
                    "memory limit",
                    "memory request",
                    "creation_time",
                    "restarts",
                    "addresses",
                    "containers",
                    "status",
                ],
                rows=rows,
            )
        ]
    )


@action
def get_resource_yaml(event: KubernetesResourceEvent):
    """
    Export Kubernetes resources from the cluster as the yaml file.
    Expects the kind of resource, its name and namespace.
    """
    resource = event.get_resource()
    if not resource:
        logging.error(f"resource not found...")
        return

    resource_kind = resource.kind
    namespace: str = resource.metadata.namespace
    name: str = resource.metadata.name

    try:
        loaded_resource = ResourceLoader.read_resource(
            kind=resource_kind,
            namespace=namespace,
            name=name,
        ).obj
        resource_yaml = hikaru.get_yaml(loaded_resource)

        event.add_enrichment(
            [
                MarkdownBlock(f"Your YAML file for {resource_kind} {namespace}/{name}"),
                FileBlock(f"{name}.yaml", resource_yaml.encode()),
            ],
        )
    except KeyError:
        logging.error(f"{resource_kind} is not supported resource kind")
    except kubernetes.client.exceptions.ApiException as exc:
        if exc.status == 404:
            logging.error(f"{resource_kind.title()} {namespace}/{name} was not found")
        else:
            logging.error(f"A following error occurred: {str(exc)}")
    except Exception as exc:
        logging.error("Unexpected error occurred!")
        logging.exception(exc)
