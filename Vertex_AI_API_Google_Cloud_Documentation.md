# Vertex AI API  |  Google Cloud Documentation

Train high-quality custom machine learning models with minimal machine learning expertise and effort.

## Service: aiplatform.googleapis.com

To call this service, we recommend that you use the Google-provided [client libraries](https://cloud.google.com/apis/docs/client-libraries-explained). If your application needs to use your own libraries to call this service, use the following information when you make the API requests.

### Discovery document

A [Discovery Document](https://developers.google.com/discovery/v1/reference/apis) is a machine-readable specification for describing and consuming REST APIs. It is used to build client libraries, IDE plugins, and other tools that interact with Google APIs. One service may provide multiple discovery documents. This service provides the following discovery documents:

-   [https://aiplatform.googleapis.com/$discovery/rest?version=v1](https://aiplatform.googleapis.com/$discovery/rest?version=v1)

-   [https://aiplatform.googleapis.com/$discovery/rest?version=v1beta1](https://aiplatform.googleapis.com/$discovery/rest?version=v1beta1)

### Service endpoint

A [service endpoint](https://cloud.google.com/apis/design/glossary#api_service_endpoint) is a base URL that specifies the network address of an API service. One service might have multiple service endpoints. This service has the following service endpoints and all URIs below are relative to these service endpoints:

-   `https://aiplatform.googleapis.com`

-   `https://africa-south1-aiplatform.googleapis.com`
-   `https://asia-east1-aiplatform.googleapis.com`

-   `https://asia-east2-aiplatform.googleapis.com`
-   `https://asia-northeast1-aiplatform.googleapis.com`

-   `https://asia-northeast2-aiplatform.googleapis.com`
-   `https://asia-northeast3-aiplatform.googleapis.com`

-   `https://asia-south1-aiplatform.googleapis.com`
-   `https://asia-southeast1-aiplatform.googleapis.com`

-   `https://asia-southeast2-aiplatform.googleapis.com`
-   `https://australia-southeast1-aiplatform.googleapis.com`

-   `https://australia-southeast2-aiplatform.googleapis.com`
-   `https://europe-central2-aiplatform.googleapis.com`

-   `https://europe-north1-aiplatform.googleapis.com`
-   `https://europe-southwest1-aiplatform.googleapis.com`

-   `https://europe-west1-aiplatform.googleapis.com`
-   `https://europe-west2-aiplatform.googleapis.com`

-   `https://europe-west3-aiplatform.googleapis.com`
-   `https://europe-west4-aiplatform.googleapis.com`

-   `https://europe-west6-aiplatform.googleapis.com`
-   `https://europe-west8-aiplatform.googleapis.com`

-   `https://europe-west9-aiplatform.googleapis.com`
-   `https://europe-west12-aiplatform.googleapis.com`

-   `https://me-central1-aiplatform.googleapis.com`
-   `https://me-central2-aiplatform.googleapis.com`

-   `https://me-west1-aiplatform.googleapis.com`
-   `https://northamerica-northeast1-aiplatform.googleapis.com`

-   `https://northamerica-northeast2-aiplatform.googleapis.com`
-   `https://southamerica-east1-aiplatform.googleapis.com`

-   `https://southamerica-west1-aiplatform.googleapis.com`
-   `https://us-central1-aiplatform.googleapis.com`

-   `https://us-east1-aiplatform.googleapis.com`
-   `https://us-east4-aiplatform.googleapis.com`

-   `https://us-south1-aiplatform.googleapis.com`
-   `https://us-west1-aiplatform.googleapis.com`

-   `https://us-west2-aiplatform.googleapis.com`
-   `https://us-west3-aiplatform.googleapis.com`

-   `https://us-west4-aiplatform.googleapis.com`
-   `https://us-east5-aiplatform.googleapis.com`

See [Feature availability](https://docs.cloud.google.com/vertex-ai/docs/general/locations#feature-availability) for the supported features for each region.

 | Methods |
| --- |
| `[upload](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/media/upload)` | `POST /v1/{parent}/ragFiles:upload`  
`POST /upload/v1/{parent}/ragFiles:upload`  
Upload a file into a RagCorpus. |

## REST Resource: [v1.operations](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/operations)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/operations/cancel)` | `POST /v1/{name}:cancel`  
Starts asynchronous cancellation on a long-running operation. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/operations/delete)` | `DELETE /v1/{name}`  
Deletes a long-running operation. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/operations/get)` | `GET /v1/{name}`  
Gets the latest state of a long-running operation. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/operations/list)` | `GET /v1/operations`  
Lists operations that match the specified filter in the request. |
| `[wait](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/operations/wait)` | `POST /v1/{name}:wait`  
Waits until the specified long-running operation is done or reaches at most a specified timeout, returning the latest state. |

## REST Resource: [v1.projects.locations](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations)

 | Methods |
| --- |
| `[askContexts](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations/askContexts)` | `POST /v1/{parent}:askContexts`  
Agentic Retrieval Ask API for RAG. |
| `[asyncRetrieveContexts](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations/asyncRetrieveContexts)` | `POST /v1/{parent}:asyncRetrieveContexts`  
Asynchronous API to retrieves relevant contexts for a query. |
| `[augmentPrompt](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations/augmentPrompt)` | `POST /v1/{parent}:augmentPrompt`  
Given an input prompt, it returns augmented prompt from vertex rag store to guide LLM towards generating grounded responses. |
| `[corroborateContent](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations/corroborateContent)` | `POST /v1/{parent}:corroborateContent`  
Given an input text, it returns a score that evaluates the factuality of the text. |
| `[deploy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations/deploy)` | `POST /v1/{destination}:deploy`  
Deploys a model to a new endpoint. |
| `[evaluateInstances](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations/evaluateInstances)` | `POST /v1/{location}:evaluateInstances`  
Evaluates instances based on a given metric. |
| `[generateSyntheticData](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations/generateSyntheticData)` | `POST /v1/{location}:generateSyntheticData`  
Generates synthetic (artificial) data based on a description |
| `[getRagEngineConfig](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations/getRagEngineConfig)` | `GET /v1/{name}`  
Gets a RagEngineConfig. |
| `[retrieveContexts](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations/retrieveContexts)` | `POST /v1/{parent}:retrieveContexts`  
Retrieves relevant contexts for a query. |
| `[updateRagEngineConfig](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations/updateRagEngineConfig)` | `PATCH /v1/{ragEngineConfig.name}`  
Updates a RagEngineConfig. |

## REST Resource: [v1.projects.locations.batchPredictionJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.batchPredictionJobs)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.batchPredictionJobs/cancel)` | `POST /v1/{name}:cancel`  
Cancels a BatchPredictionJob. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.batchPredictionJobs/create)` | `POST /v1/{parent}/batchPredictionJobs`  
Creates a BatchPredictionJob. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.batchPredictionJobs/delete)` | `DELETE /v1/{name}`  
Deletes a BatchPredictionJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.batchPredictionJobs/get)` | `GET /v1/{name}`  
Gets a BatchPredictionJob |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.batchPredictionJobs/list)` | `GET /v1/{parent}/batchPredictionJobs`  
Lists BatchPredictionJobs in a Location. |

## REST Resource: [v1.projects.locations.cachedContents](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.cachedContents)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.cachedContents/create)` | `POST /v1/{parent}/cachedContents`  
Creates cached content, this call will initialize the cached content in the data storage, and users need to pay for the cache data storage. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.cachedContents/delete)` | `DELETE /v1/{name}`  
Deletes cached content |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.cachedContents/get)` | `GET /v1/{name}`  
Gets cached content configurations |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.cachedContents/list)` | `GET /v1/{parent}/cachedContents`  
Lists cached contents in a project |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.cachedContents/patch)` | `PATCH /v1/{cachedContent.name}`  
Updates cached content configurations |

## REST Resource: [v1.projects.locations.customJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.customJobs)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.customJobs/cancel)` | `POST /v1/{name}:cancel`  
Cancels a CustomJob. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.customJobs/create)` | `POST /v1/{parent}/customJobs`  
Creates a CustomJob. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.customJobs/delete)` | `DELETE /v1/{name}`  
Deletes a CustomJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.customJobs/get)` | `GET /v1/{name}`  
Gets a CustomJob. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.customJobs/list)` | `GET /v1/{parent}/customJobs`  
Lists CustomJobs in a Location. |

## REST Resource: [v1.projects.locations.datasets](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets/create)` | `POST /v1/{parent}/datasets`  
Creates a Dataset. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets/delete)` | `DELETE /v1/{name}`  
Deletes a Dataset. |
| `[export](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets/export)` | `POST /v1/{name}:export`  
Exports data from a Dataset. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets/get)` | `GET /v1/{name}`  
Gets a Dataset. |
| `[import](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets/import)` | `POST /v1/{name}:import`  
Imports data into a Dataset. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets/list)` | `GET /v1/{parent}/datasets`  
Lists Datasets in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets/patch)` | `PATCH /v1/{dataset.name}`  
Updates a Dataset. |
| `[searchDataItems](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets/searchDataItems)` | `GET /v1/{dataset}:searchDataItems`  
Searches DataItems in a Dataset. |

## REST Resource: [v1.projects.locations.datasets.annotationSpecs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.annotationSpecs)

 | Methods |
| --- |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.annotationSpecs/get)` | `GET /v1/{name}`  
Gets an AnnotationSpec. |

## REST Resource: [v1.projects.locations.datasets.dataItems](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.dataItems)

 | Methods |
| --- |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.dataItems/list)` | `GET /v1/{parent}/dataItems`  
Lists DataItems in a Dataset. |

## REST Resource: [v1.projects.locations.datasets.dataItems.annotations](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.dataItems.annotations)

 | Methods |
| --- |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.dataItems.annotations/list)` | `GET /v1/{parent}/annotations`  
Lists Annotations belongs to a dataitem. |

## REST Resource: [v1.projects.locations.datasets.datasetVersions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.datasetVersions)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.datasetVersions/create)` | `POST /v1/{parent}/datasetVersions`  
Create a version from a Dataset. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.datasetVersions/delete)` | `DELETE /v1/{name}`  
Deletes a Dataset version. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.datasetVersions/get)` | `GET /v1/{name}`  
Gets a Dataset version. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.datasetVersions/list)` | `GET /v1/{parent}/datasetVersions`  
Lists DatasetVersions in a Dataset. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.datasetVersions/patch)` | `PATCH /v1/{datasetVersion.name}`  
Updates a DatasetVersion. |
| `[restore](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.datasetVersions/restore)` | `GET /v1/{name}:restore`  
Restores a dataset version. |

## REST Resource: [v1.projects.locations.datasets.savedQueries](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.savedQueries)

 | Methods |
| --- |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.savedQueries/delete)` | `DELETE /v1/{name}`  
Deletes a SavedQuery. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.datasets.savedQueries/list)` | `GET /v1/{parent}/savedQueries`  
Lists SavedQueries in a Dataset. |

## REST Resource: [v1.projects.locations.deploymentResourcePools](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.deploymentResourcePools)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.deploymentResourcePools/create)` | `POST /v1/{parent}/deploymentResourcePools`  
Create a DeploymentResourcePool. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.deploymentResourcePools/delete)` | `DELETE /v1/{name}`  
Delete a DeploymentResourcePool. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.deploymentResourcePools/get)` | `GET /v1/{name}`  
Get a DeploymentResourcePool. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.deploymentResourcePools/list)` | `GET /v1/{parent}/deploymentResourcePools`  
List DeploymentResourcePools in a location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.deploymentResourcePools/patch)` | `PATCH /v1/{deploymentResourcePool.name}`  
Update a DeploymentResourcePool. |
| `[queryDeployedModels](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.deploymentResourcePools/queryDeployedModels)` | `GET /v1/{deploymentResourcePool}:queryDeployedModels`  
List DeployedModels that have been deployed on this DeploymentResourcePool. |

## REST Resource: [v1.projects.locations.endpoints](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/create)` | `POST /v1/{parent}/endpoints`  
Creates an Endpoint. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/delete)` | `DELETE /v1/{name}`  
Deletes an Endpoint. |
| `[deployModel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/deployModel)` | `POST /v1/{endpoint}:deployModel`  
Deploys a Model into this Endpoint, creating a DeployedModel within it. |
| `[directPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/directPredict)` | `POST /v1/{endpoint}:directPredict`  
Perform an unary online prediction request to a gRPC model server for Vertex first-party products and frameworks. |
| `[directRawPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/directRawPredict)` | `POST /v1/{endpoint}:directRawPredict`  
Perform an unary online prediction request to a gRPC model server for custom containers. |
| `[explain](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/explain)` | `POST /v1/{endpoint}:explain`  
Perform an online explanation. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/get)` | `GET /v1/{name}`  
Gets an Endpoint. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/list)` | `GET /v1/{parent}/endpoints`  
Lists Endpoints in a Location. |
| `[mutateDeployedModel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/mutateDeployedModel)` | `POST /v1/{endpoint}:mutateDeployedModel`  
Updates an existing deployed model. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/patch)` | `PATCH /v1/{endpoint.name}`  
Updates an Endpoint. |
| `[predict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/predict)` | `POST /v1/{endpoint}:predict`  
Perform an online prediction. |
| `[rawPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/rawPredict)` | `POST /v1/{endpoint}:rawPredict`  
Perform an online prediction with an arbitrary HTTP payload. |
| `[serverStreamingPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/serverStreamingPredict)` | `POST /v1/{endpoint}:serverStreamingPredict`  
Perform a server-side streaming online prediction request for Vertex LLM streaming. |
| `[streamRawPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/streamRawPredict)` | `POST /v1/{endpoint}:streamRawPredict`  
Perform a streaming online prediction with an arbitrary HTTP payload. |
| `[undeployModel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/undeployModel)` | `POST /v1/{endpoint}:undeployModel`  
Undeploys a Model from an Endpoint, removing a DeployedModel from it, and freeing all resources it's using. |
| `[update](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/update)` | `POST /v1/{endpoint.name}:update`  
Updates an Endpoint with a long running operation. |

## REST Resource: [v1.projects.locations.featureGroups](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups/create)` | `POST /v1/{parent}/featureGroups`  
Creates a new FeatureGroup in a given project and location. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups/delete)` | `DELETE /v1/{name}`  
Deletes a single FeatureGroup. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups/get)` | `GET /v1/{name}`  
Gets details of a single FeatureGroup. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups/getIamPolicy)` | `POST /v1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups/list)` | `GET /v1/{parent}/featureGroups`  
Lists FeatureGroups in a given project and location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups/patch)` | `PATCH /v1/{featureGroup.name}`  
Updates the parameters of a single FeatureGroup. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups/setIamPolicy)` | `POST /v1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups/testIamPermissions)` | `POST /v1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |

## REST Resource: [v1.projects.locations.featureGroups.features](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups.features)

 | Methods |
| --- |
| `[batchCreate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups.features/batchCreate)` | `POST /v1/{parent}/features:batchCreate`  
Creates a batch of Features in a given FeatureGroup. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups.features/create)` | `POST /v1/{parent}/features`  
Creates a new Feature in a given FeatureGroup. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups.features/delete)` | `DELETE /v1/{name}`  
Deletes a single Feature. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups.features/get)` | `GET /v1/{name}`  
Gets details of a single Feature. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups.features/list)` | `GET /v1/{parent}/features`  
Lists Features in a given FeatureGroup. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureGroups.features/patch)` | `PATCH /v1/{feature.name}`  
Updates the parameters of a single Feature. |

## REST Resource: [v1.projects.locations.featureOnlineStores](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores/create)` | `POST /v1/{parent}/featureOnlineStores`  
Creates a new FeatureOnlineStore in a given project and location. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores/delete)` | `DELETE /v1/{name}`  
Deletes a single FeatureOnlineStore. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores/get)` | `GET /v1/{name}`  
Gets details of a single FeatureOnlineStore. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores/getIamPolicy)` | `POST /v1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores/list)` | `GET /v1/{parent}/featureOnlineStores`  
Lists FeatureOnlineStores in a given project and location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores/patch)` | `PATCH /v1/{featureOnlineStore.name}`  
Updates the parameters of a single FeatureOnlineStore. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores/setIamPolicy)` | `POST /v1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores/testIamPermissions)` | `POST /v1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |

## REST Resource: [v1.projects.locations.featureOnlineStores.featureViews](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/create)` | `POST /v1/{parent}/featureViews`  
Creates a new FeatureView in a given FeatureOnlineStore. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/delete)` | `DELETE /v1/{name}`  
Deletes a single FeatureView. |
| `[directWrite](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/directWrite)` | `POST /v1/{featureView}:directWrite`  
Bidirectional streaming RPC to directly write to feature values in a feature view. |
| `[fetchFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/fetchFeatureValues)` | `POST /v1/{featureView}:fetchFeatureValues`  
Fetch feature values under a FeatureView. |
| `[generateFetchAccessToken](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/generateFetchAccessToken)` | `POST /v1/{featureView}:generateFetchAccessToken`  
RPC to generate an access token for the given feature view. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/get)` | `GET /v1/{name}`  
Gets details of a single FeatureView. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/getIamPolicy)` | `POST /v1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/list)` | `GET /v1/{parent}/featureViews`  
Lists FeatureViews in a given FeatureOnlineStore. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/patch)` | `PATCH /v1/{featureView.name}`  
Updates the parameters of a single FeatureView. |
| `[searchNearestEntities](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/searchNearestEntities)` | `POST /v1/{featureView}:searchNearestEntities`  
Search the nearest entities under a FeatureView. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/setIamPolicy)` | `POST /v1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[sync](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/sync)` | `POST /v1/{featureView}:sync`  
Triggers on-demand sync for the FeatureView. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews/testIamPermissions)` | `POST /v1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |

## REST Resource: [v1.projects.locations.featureOnlineStores.featureViews.featureViewSyncs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews.featureViewSyncs)

 | Methods |
| --- |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews.featureViewSyncs/get)` | `GET /v1/{name}`  
Gets details of a single FeatureViewSync. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featureOnlineStores.featureViews.featureViewSyncs/list)` | `GET /v1/{parent}/featureViewSyncs`  
Lists FeatureViewSyncs in a given FeatureView. |

## REST Resource: [v1.projects.locations.featurestores](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores)

 | Methods |
| --- |
| `[batchReadFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores/batchReadFeatureValues)` | `POST /v1/{featurestore}:batchReadFeatureValues`  
Batch reads Feature values from a Featurestore. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores/create)` | `POST /v1/{parent}/featurestores`  
Creates a new Featurestore in a given project and location. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores/delete)` | `DELETE /v1/{name}`  
Deletes a single Featurestore. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores/get)` | `GET /v1/{name}`  
Gets details of a single Featurestore. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores/getIamPolicy)` | `POST /v1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores/list)` | `GET /v1/{parent}/featurestores`  
Lists Featurestores in a given project and location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores/patch)` | `PATCH /v1/{featurestore.name}`  
Updates the parameters of a single Featurestore. |
| `[searchFeatures](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores/searchFeatures)` | `GET /v1/{location}/featurestores:searchFeatures`  
Searches Features matching a query in a given project. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores/setIamPolicy)` | `POST /v1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores/testIamPermissions)` | `POST /v1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |

## REST Resource: [v1.projects.locations.featurestores.entityTypes](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/create)` | `POST /v1/{parent}/entityTypes`  
Creates a new EntityType in a given Featurestore. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/delete)` | `DELETE /v1/{name}`  
Deletes a single EntityType. |
| `[deleteFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/deleteFeatureValues)` | `POST /v1/{entityType}:deleteFeatureValues`  
Delete Feature values from Featurestore. |
| `[exportFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/exportFeatureValues)` | `POST /v1/{entityType}:exportFeatureValues`  
Exports Feature values from all the entities of a target EntityType. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/get)` | `GET /v1/{name}`  
Gets details of a single EntityType. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/getIamPolicy)` | `POST /v1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[importFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/importFeatureValues)` | `POST /v1/{entityType}:importFeatureValues`  
Imports Feature values into the Featurestore from a source storage. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/list)` | `GET /v1/{parent}/entityTypes`  
Lists EntityTypes in a given Featurestore. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/patch)` | `PATCH /v1/{entityType.name}`  
Updates the parameters of a single EntityType. |
| `[readFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/readFeatureValues)` | `POST /v1/{entityType}:readFeatureValues`  
Reads Feature values of a specific entity of an EntityType. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/setIamPolicy)` | `POST /v1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[streamingReadFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/streamingReadFeatureValues)` | `POST /v1/{entityType}:streamingReadFeatureValues`  
Reads Feature values for multiple entities. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/testIamPermissions)` | `POST /v1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |
| `[writeFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes/writeFeatureValues)` | `POST /v1/{entityType}:writeFeatureValues`  
Writes Feature values of one or more entities of an EntityType. |

## REST Resource: [v1.projects.locations.featurestores.entityTypes.features](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes.features)

 | Methods |
| --- |
| `[batchCreate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes.features/batchCreate)` | `POST /v1/{parent}/features:batchCreate`  
Creates a batch of Features in a given EntityType. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes.features/create)` | `POST /v1/{parent}/features`  
Creates a new Feature in a given EntityType. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes.features/delete)` | `DELETE /v1/{name}`  
Deletes a single Feature. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes.features/get)` | `GET /v1/{name}`  
Gets details of a single Feature. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes.features/list)` | `GET /v1/{parent}/features`  
Lists Features in a given EntityType. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.featurestores.entityTypes.features/patch)` | `PATCH /v1/{feature.name}`  
Updates the parameters of a single Feature. |

## REST Resource: [v1.projects.locations.hyperparameterTuningJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.hyperparameterTuningJobs)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.hyperparameterTuningJobs/cancel)` | `POST /v1/{name}:cancel`  
Cancels a HyperparameterTuningJob. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.hyperparameterTuningJobs/create)` | `POST /v1/{parent}/hyperparameterTuningJobs`  
Creates a HyperparameterTuningJob |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.hyperparameterTuningJobs/delete)` | `DELETE /v1/{name}`  
Deletes a HyperparameterTuningJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.hyperparameterTuningJobs/get)` | `GET /v1/{name}`  
Gets a HyperparameterTuningJob |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.hyperparameterTuningJobs/list)` | `GET /v1/{parent}/hyperparameterTuningJobs`  
Lists HyperparameterTuningJobs in a Location. |

## REST Resource: [v1.projects.locations.indexEndpoints](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexEndpoints)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexEndpoints/create)` | `POST /v1/{parent}/indexEndpoints`  
Creates an IndexEndpoint. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexEndpoints/delete)` | `DELETE /v1/{name}`  
Deletes an IndexEndpoint. |
| `[deployIndex](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexEndpoints/deployIndex)` | `POST /v1/{indexEndpoint}:deployIndex`  
Deploys an Index into this IndexEndpoint, creating a DeployedIndex within it. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexEndpoints/get)` | `GET /v1/{name}`  
Gets an IndexEndpoint. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexEndpoints/list)` | `GET /v1/{parent}/indexEndpoints`  
Lists IndexEndpoints in a Location. |
| `[mutateDeployedIndex](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexEndpoints/mutateDeployedIndex)` | `POST /v1/{indexEndpoint}:mutateDeployedIndex`  
Update an existing DeployedIndex under an IndexEndpoint. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexEndpoints/patch)` | `PATCH /v1/{indexEndpoint.name}`  
Updates an IndexEndpoint. |
| `[undeployIndex](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexEndpoints/undeployIndex)` | `POST /v1/{indexEndpoint}:undeployIndex`  
Undeploys an Index from an IndexEndpoint, removing a DeployedIndex from it, and freeing all resources it's using. |

## REST Resource: [v1.projects.locations.indexes](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexes)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexes/create)` | `POST /v1/{parent}/indexes`  
Creates an Index. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexes/delete)` | `DELETE /v1/{name}`  
Deletes an Index. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexes/get)` | `GET /v1/{name}`  
Gets an Index. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexes/list)` | `GET /v1/{parent}/indexes`  
Lists Indexes in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexes/patch)` | `PATCH /v1/{index.name}`  
Updates an Index. |
| `[removeDatapoints](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexes/removeDatapoints)` | `POST /v1/{index}:removeDatapoints`  
Remove Datapoints from an Index. |
| `[upsertDatapoints](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.indexes/upsertDatapoints)` | `POST /v1/{index}:upsertDatapoints`  
Add/update Datapoints into an Index. |

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores/create)` | `POST /v1/{parent}/metadataStores`  
Initializes a MetadataStore, including allocation of resources. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores/delete)` | `DELETE /v1/{name}`  
Deletes a single MetadataStore and all its child resources (Artifacts, Executions, and Contexts). |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores/get)` | `GET /v1/{name}`  
Retrieves a specific MetadataStore. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores/list)` | `GET /v1/{parent}/metadataStores`  
Lists MetadataStores for a Location. |

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.artifacts/create)` | `POST /v1/{parent}/artifacts`  
Creates an Artifact associated with a MetadataStore. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.artifacts/delete)` | `DELETE /v1/{name}`  
Deletes an Artifact. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.artifacts/get)` | `GET /v1/{name}`  
Retrieves a specific Artifact. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.artifacts/list)` | `GET /v1/{parent}/artifacts`  
Lists Artifacts in the MetadataStore. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.artifacts/patch)` | `PATCH /v1/{artifact.name}`  
Updates a stored Artifact. |
| `[purge](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.artifacts/purge)` | `POST /v1/{parent}/artifacts:purge`  
Purges Artifacts. |
| `[queryArtifactLineageSubgraph](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.artifacts/queryArtifactLineageSubgraph)` | `GET /v1/{artifact}:queryArtifactLineageSubgraph`  
Retrieves lineage of an Artifact represented through Artifacts and Executions connected by Event edges and returned as a LineageSubgraph. |

## REST Resource: [v1.projects.locations.metadataStores.contexts](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.contexts)

 | Methods |
| --- |
| `[addContextArtifactsAndExecutions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.contexts/addContextArtifactsAndExecutions)` | `POST /v1/{context}:addContextArtifactsAndExecutions`  
Adds a set of Artifacts and Executions to a Context. |
| `[addContextChildren](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.contexts/addContextChildren)` | `POST /v1/{context}:addContextChildren`  
Adds a set of Contexts as children to a parent Context. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.contexts/create)` | `POST /v1/{parent}/contexts`  
Creates a Context associated with a MetadataStore. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.contexts/delete)` | `DELETE /v1/{name}`  
Deletes a stored Context. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.contexts/get)` | `GET /v1/{name}`  
Retrieves a specific Context. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.contexts/list)` | `GET /v1/{parent}/contexts`  
Lists Contexts on the MetadataStore. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.contexts/patch)` | `PATCH /v1/{context.name}`  
Updates a stored Context. |
| `[purge](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.contexts/purge)` | `POST /v1/{parent}/contexts:purge`  
Purges Contexts. |
| `[queryContextLineageSubgraph](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.contexts/queryContextLineageSubgraph)` | `GET /v1/{context}:queryContextLineageSubgraph`  
Retrieves Artifacts and Executions within the specified Context, connected by Event edges and returned as a LineageSubgraph. |
| `[removeContextChildren](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.contexts/removeContextChildren)` | `POST /v1/{context}:removeContextChildren`  
Remove a set of children contexts from a parent Context. |

 | Methods |
| --- |
| `[addExecutionEvents](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.executions/addExecutionEvents)` | `POST /v1/{execution}:addExecutionEvents`  
Adds Events to the specified Execution. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.executions/create)` | `POST /v1/{parent}/executions`  
Creates an Execution associated with a MetadataStore. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.executions/delete)` | `DELETE /v1/{name}`  
Deletes an Execution. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.executions/get)` | `GET /v1/{name}`  
Retrieves a specific Execution. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.executions/list)` | `GET /v1/{parent}/executions`  
Lists Executions in the MetadataStore. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.executions/patch)` | `PATCH /v1/{execution.name}`  
Updates a stored Execution. |
| `[purge](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.executions/purge)` | `POST /v1/{parent}/executions:purge`  
Purges Executions. |
| `[queryExecutionInputsAndOutputs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.executions/queryExecutionInputsAndOutputs)` | `GET /v1/{execution}:queryExecutionInputsAndOutputs`  
Obtains the set of input and output Artifacts for this Execution, in the form of LineageSubgraph that also contains the Execution and connecting Events. |

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.metadataSchemas/create)` | `POST /v1/{parent}/metadataSchemas`  
Creates a MetadataSchema. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.metadataSchemas/get)` | `GET /v1/{name}`  
Retrieves a specific MetadataSchema. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.metadataStores.metadataSchemas/list)` | `GET /v1/{parent}/metadataSchemas`  
Lists MetadataSchemas. |

## REST Resource: [v1.projects.locations.migratableResources](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.migratableResources)

 | Methods |
| --- |
| `[batchMigrate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.migratableResources/batchMigrate)` | `POST /v1/{parent}/migratableResources:batchMigrate`  
Batch migrates resources from ml.googleapis.com, automl.googleapis.com, and datalabeling.googleapis.com to Vertex AI. |
| `[search](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.migratableResources/search)` | `POST /v1/{parent}/migratableResources:search`  
Searches all of the resources in automl.googleapis.com, datalabeling.googleapis.com and ml.googleapis.com that can be migrated to Vertex AI's given location. |

## REST Resource: [v1.projects.locations.modelDeploymentMonitoringJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.modelDeploymentMonitoringJobs)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.modelDeploymentMonitoringJobs/create)` | `POST /v1/{parent}/modelDeploymentMonitoringJobs`  
Creates a ModelDeploymentMonitoringJob. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.modelDeploymentMonitoringJobs/delete)` | `DELETE /v1/{name}`  
Deletes a ModelDeploymentMonitoringJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.modelDeploymentMonitoringJobs/get)` | `GET /v1/{name}`  
Gets a ModelDeploymentMonitoringJob. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.modelDeploymentMonitoringJobs/list)` | `GET /v1/{parent}/modelDeploymentMonitoringJobs`  
Lists ModelDeploymentMonitoringJobs in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.modelDeploymentMonitoringJobs/patch)` | `PATCH /v1/{modelDeploymentMonitoringJob.name}`  
Updates a ModelDeploymentMonitoringJob. |
| `[pause](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.modelDeploymentMonitoringJobs/pause)` | `POST /v1/{name}:pause`  
Pauses a ModelDeploymentMonitoringJob. |
| `[resume](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.modelDeploymentMonitoringJobs/resume)` | `POST /v1/{name}:resume`  
Resumes a paused ModelDeploymentMonitoringJob. |
| `[searchModelDeploymentMonitoringStatsAnomalies](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.modelDeploymentMonitoringJobs/searchModelDeploymentMonitoringStatsAnomalies)` | `POST /v1/{modelDeploymentMonitoringJob}:searchModelDeploymentMonitoringStatsAnomalies`  
Searches Model Monitoring Statistics generated within a given time window. |

## REST Resource: [v1.projects.locations.models](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models)

 | Methods |
| --- |
| `[copy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/copy)` | `POST /v1/{parent}/models:copy`  
Copies an already existing Vertex AI Model into the specified Location. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/delete)` | `DELETE /v1/{name}`  
Deletes a Model. |
| `[deleteVersion](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/deleteVersion)` | `DELETE /v1/{name}:deleteVersion`  
Deletes a Model version. |
| `[export](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/export)` | `POST /v1/{name}:export`  
Exports a trained, exportable Model to a location specified by the user. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/get)` | `GET /v1/{name}`  
Gets a Model. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/getIamPolicy)` | `POST /v1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/list)` | `GET /v1/{parent}/models`  
Lists Models in a Location. |
| `[listCheckpoints](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/listCheckpoints)` | `GET /v1/{name}:listCheckpoints`  
Lists checkpoints of the specified model version. |
| `[listVersions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/listVersions)` | `GET /v1/{name}:listVersions`  
Lists versions of the specified model. |
| `[mergeVersionAliases](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/mergeVersionAliases)` | `POST /v1/{name}:mergeVersionAliases`  
Merges a set of aliases for a Model version. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/patch)` | `PATCH /v1/{model.name}`  
Updates a Model. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/setIamPolicy)` | `POST /v1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/testIamPermissions)` | `POST /v1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |
| `[updateExplanationDataset](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/updateExplanationDataset)` | `POST /v1/{model}:updateExplanationDataset`  
Incrementally update the dataset used for an examples model. |
| `[upload](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models/upload)` | `POST /v1/{parent}/models:upload`  
Uploads a Model artifact into Vertex AI. |

## REST Resource: [v1.projects.locations.models.evaluations](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models.evaluations)

 | Methods |
| --- |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models.evaluations/get)` | `GET /v1/{name}`  
Gets a ModelEvaluation. |
| `[import](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models.evaluations/import)` | `POST /v1/{parent}/evaluations:import`  
Imports an externally generated ModelEvaluation. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models.evaluations/list)` | `GET /v1/{parent}/evaluations`  
Lists ModelEvaluations in a Model. |

## REST Resource: [v1.projects.locations.models.evaluations.slices](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models.evaluations.slices)

 | Methods |
| --- |
| `[batchImport](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models.evaluations.slices/batchImport)` | `POST /v1/{parent}:batchImport`  
Imports a list of externally generated EvaluatedAnnotations. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models.evaluations.slices/get)` | `GET /v1/{name}`  
Gets a ModelEvaluationSlice. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.models.evaluations.slices/list)` | `GET /v1/{parent}/slices`  
Lists ModelEvaluationSlices in a ModelEvaluation. |

## REST Resource: [v1.projects.locations.nasJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.nasJobs)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.nasJobs/cancel)` | `POST /v1/{name}:cancel`  
Cancels a NasJob. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.nasJobs/create)` | `POST /v1/{parent}/nasJobs`  
Creates a NasJob |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.nasJobs/delete)` | `DELETE /v1/{name}`  
Deletes a NasJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.nasJobs/get)` | `GET /v1/{name}`  
Gets a NasJob |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.nasJobs/list)` | `GET /v1/{parent}/nasJobs`  
Lists NasJobs in a Location. |

## REST Resource: [v1.projects.locations.nasJobs.nasTrialDetails](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.nasJobs.nasTrialDetails)

 | Methods |
| --- |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.nasJobs.nasTrialDetails/get)` | `GET /v1/{name}`  
Gets a NasTrialDetail. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.nasJobs.nasTrialDetails/list)` | `GET /v1/{parent}/nasTrialDetails`  
List top NasTrialDetails of a NasJob. |

## REST Resource: [v1.projects.locations.notebookExecutionJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookExecutionJobs)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookExecutionJobs/create)` | `POST /v1/{parent}/notebookExecutionJobs`  
Creates a NotebookExecutionJob. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookExecutionJobs/delete)` | `DELETE /v1/{name}`  
Deletes a NotebookExecutionJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookExecutionJobs/get)` | `GET /v1/{name}`  
Gets a NotebookExecutionJob. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookExecutionJobs/list)` | `GET /v1/{parent}/notebookExecutionJobs`  
Lists NotebookExecutionJobs in a Location. |

## REST Resource: [v1.projects.locations.notebookRuntimeTemplates](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimeTemplates)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimeTemplates/create)` | `POST /v1/{parent}/notebookRuntimeTemplates`  
Creates a NotebookRuntimeTemplate. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimeTemplates/delete)` | `DELETE /v1/{name}`  
Deletes a NotebookRuntimeTemplate. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimeTemplates/get)` | `GET /v1/{name}`  
Gets a NotebookRuntimeTemplate. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimeTemplates/getIamPolicy)` | `POST /v1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimeTemplates/list)` | `GET /v1/{parent}/notebookRuntimeTemplates`  
Lists NotebookRuntimeTemplates in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimeTemplates/patch)` | `PATCH /v1/{notebookRuntimeTemplate.name}`  
Updates a NotebookRuntimeTemplate. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimeTemplates/setIamPolicy)` | `POST /v1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimeTemplates/testIamPermissions)` | `POST /v1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |

## REST Resource: [v1.projects.locations.notebookRuntimes](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimes)

 | Methods |
| --- |
| `[assign](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimes/assign)` | `POST /v1/{parent}/notebookRuntimes:assign`  
Assigns a NotebookRuntime to a user for a particular Notebook file. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimes/delete)` | `DELETE /v1/{name}`  
Deletes a NotebookRuntime. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimes/get)` | `GET /v1/{name}`  
Gets a NotebookRuntime. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimes/list)` | `GET /v1/{parent}/notebookRuntimes`  
Lists NotebookRuntimes in a Location. |
| `[start](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimes/start)` | `POST /v1/{name}:start`  
Starts a NotebookRuntime. |
| `[stop](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimes/stop)` | `POST /v1/{name}:stop`  
Stops a NotebookRuntime. |
| `[upgrade](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.notebookRuntimes/upgrade)` | `POST /v1/{name}:upgrade`  
Upgrades a NotebookRuntime. |

## REST Resource: [v1.projects.locations.operations](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.operations)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.operations/cancel)` | `POST /v1/{name}:cancel`  
Starts asynchronous cancellation on a long-running operation. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.operations/delete)` | `DELETE /v1/{name}`  
Deletes a long-running operation. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.operations/get)` | `GET /v1/{name}`  
Gets the latest state of a long-running operation. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.operations/list)` | `GET /v1/{name}/operations`  
Lists operations that match the specified filter in the request. |
| `[wait](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.operations/wait)` | `POST /v1/{name}:wait`  
Waits until the specified long-running operation is done or reaches at most a specified timeout, returning the latest state. |

## REST Resource: [v1.projects.locations.persistentResources](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.persistentResources)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.persistentResources/create)` | `POST /v1/{parent}/persistentResources`  
Creates a PersistentResource. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.persistentResources/delete)` | `DELETE /v1/{name}`  
Deletes a PersistentResource. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.persistentResources/get)` | `GET /v1/{name}`  
Gets a PersistentResource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.persistentResources/list)` | `GET /v1/{parent}/persistentResources`  
Lists PersistentResources in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.persistentResources/patch)` | `PATCH /v1/{persistentResource.name}`  
Updates a PersistentResource. |
| `[reboot](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.persistentResources/reboot)` | `POST /v1/{name}:reboot`  
Reboots a PersistentResource. |

## REST Resource: [v1.projects.locations.pipelineJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.pipelineJobs)

 | Methods |
| --- |
| `[batchCancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.pipelineJobs/batchCancel)` | `POST /v1/{parent}/pipelineJobs:batchCancel`  
Batch cancel PipelineJobs. |
| `[batchDelete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.pipelineJobs/batchDelete)` | `POST /v1/{parent}/pipelineJobs:batchDelete`  
Batch deletes PipelineJobs The Operation is atomic. |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.pipelineJobs/cancel)` | `POST /v1/{name}:cancel`  
Cancels a PipelineJob. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.pipelineJobs/create)` | `POST /v1/{parent}/pipelineJobs`  
Creates a PipelineJob. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.pipelineJobs/delete)` | `DELETE /v1/{name}`  
Deletes a PipelineJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.pipelineJobs/get)` | `GET /v1/{name}`  
Gets a PipelineJob. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.pipelineJobs/list)` | `GET /v1/{parent}/pipelineJobs`  
Lists PipelineJobs in a Location. |

## REST Resource: [v1.projects.locations.publishers.models](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.publishers.models)

 | Methods |
| --- |
| `[embedContent](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.publishers.models/embedContent)` | `POST /v1/{model}:embedContent`  
Embed content with multimodal inputs. |
| `[predict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.publishers.models/predict)` | `POST /v1/{endpoint}:predict`  
Perform an online prediction. |
| `[rawPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.publishers.models/rawPredict)` | `POST /v1/{endpoint}:rawPredict`  
Perform an online prediction with an arbitrary HTTP payload. |
| `[serverStreamingPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.publishers.models/serverStreamingPredict)` | `POST /v1/{endpoint}:serverStreamingPredict`  
Perform a server-side streaming online prediction request for Vertex LLM streaming. |
| `[streamRawPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.publishers.models/streamRawPredict)` | `POST /v1/{endpoint}:streamRawPredict`  
Perform a streaming online prediction with an arbitrary HTTP payload. |

## REST Resource: [v1.projects.locations.ragCorpora](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.ragCorpora)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.ragCorpora/create)` | `POST /v1/{parent}/ragCorpora`  
Creates a RagCorpus. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.ragCorpora/delete)` | `DELETE /v1/{name}`  
Deletes a RagCorpus. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.ragCorpora/get)` | `GET /v1/{name}`  
Gets a RagCorpus. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.ragCorpora/list)` | `GET /v1/{parent}/ragCorpora`  
Lists RagCorpora in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.ragCorpora/patch)` | `PATCH /v1/{ragCorpus.name}`  
Updates a RagCorpus. |

## REST Resource: [v1.projects.locations.ragCorpora.ragFiles](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.ragCorpora.ragFiles)

 | Methods |
| --- |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.ragCorpora.ragFiles/delete)` | `DELETE /v1/{name}`  
Deletes a RagFile. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.ragCorpora.ragFiles/get)` | `GET /v1/{name}`  
Gets a RagFile. |
| `[import](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.ragCorpora.ragFiles/import)` | `POST /v1/{parent}/ragFiles:import`  
Import files from Google Cloud Storage or Google Drive into a RagCorpus. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.ragCorpora.ragFiles/list)` | `GET /v1/{parent}/ragFiles`  
Lists RagFiles in a RagCorpus. |

## REST Resource: [v1.projects.locations.reasoningEngines](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.reasoningEngines)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.reasoningEngines/create)` | `POST /v1/{parent}/reasoningEngines`  
Creates a reasoning engine. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.reasoningEngines/delete)` | `DELETE /v1/{name}`  
Deletes a reasoning engine. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.reasoningEngines/get)` | `GET /v1/{name}`  
Gets a reasoning engine. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.reasoningEngines/list)` | `GET /v1/{parent}/reasoningEngines`  
Lists reasoning engines in a location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.reasoningEngines/patch)` | `PATCH /v1/{reasoningEngine.name}`  
Updates a reasoning engine. |
| `[query](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.reasoningEngines/query)` | `POST /v1/{name}:query`  
Queries using a reasoning engine. |
| `[streamQuery](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.reasoningEngines/streamQuery)` | `POST /v1/{name}:streamQuery`  
Streams queries using a reasoning engine. |

## REST Resource: [v1.projects.locations.schedules](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.schedules)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.schedules/create)` | `POST /v1/{parent}/schedules`  
Creates a Schedule. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.schedules/delete)` | `DELETE /v1/{name}`  
Deletes a Schedule. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.schedules/get)` | `GET /v1/{name}`  
Gets a Schedule. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.schedules/list)` | `GET /v1/{parent}/schedules`  
Lists Schedules in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.schedules/patch)` | `PATCH /v1/{schedule.name}`  
Updates an active or paused Schedule. |
| `[pause](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.schedules/pause)` | `POST /v1/{name}:pause`  
Pauses a Schedule. |
| `[resume](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.schedules/resume)` | `POST /v1/{name}:resume`  
Resumes a paused Schedule to start scheduling new runs. |

## REST Resource: [v1.projects.locations.specialistPools](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.specialistPools)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.specialistPools/create)` | `POST /v1/{parent}/specialistPools`  
Creates a SpecialistPool. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.specialistPools/delete)` | `DELETE /v1/{name}`  
Deletes a SpecialistPool as well as all Specialists in the pool. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.specialistPools/get)` | `GET /v1/{name}`  
Gets a SpecialistPool. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.specialistPools/list)` | `GET /v1/{parent}/specialistPools`  
Lists SpecialistPools in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.specialistPools/patch)` | `PATCH /v1/{specialistPool.name}`  
Updates a SpecialistPool. |

## REST Resource: [v1.projects.locations.studies](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies/create)` | `POST /v1/{parent}/studies`  
Creates a Study. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies/delete)` | `DELETE /v1/{name}`  
Deletes a Study. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies/get)` | `GET /v1/{name}`  
Gets a Study by name. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies/list)` | `GET /v1/{parent}/studies`  
Lists all the studies in a region for an associated project. |
| `[lookup](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies/lookup)` | `POST /v1/{parent}/studies:lookup`  
Looks a study up using the user-defined display\_name field instead of the fully qualified resource name. |

## REST Resource: [v1.projects.locations.studies.trials](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies.trials)

 | Methods |
| --- |
| `[addTrialMeasurement](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies.trials/addTrialMeasurement)` | `POST /v1/{trialName}:addTrialMeasurement`  
Adds a measurement of the objective metrics to a Trial. |
| `[checkTrialEarlyStoppingState](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies.trials/checkTrialEarlyStoppingState)` | `POST /v1/{trialName}:checkTrialEarlyStoppingState`  
Checks whether a Trial should stop or not. |
| `[complete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies.trials/complete)` | `POST /v1/{name}:complete`  
Marks a Trial as complete. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies.trials/create)` | `POST /v1/{parent}/trials`  
Adds a user provided Trial to a Study. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies.trials/delete)` | `DELETE /v1/{name}`  
Deletes a Trial. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies.trials/get)` | `GET /v1/{name}`  
Gets a Trial. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies.trials/list)` | `GET /v1/{parent}/trials`  
Lists the Trials associated with a Study. |
| `[listOptimalTrials](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies.trials/listOptimalTrials)` | `POST /v1/{parent}/trials:listOptimalTrials`  
Lists the pareto-optimal Trials for multi-objective Study or the optimal Trials for single-objective Study. |
| `[stop](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies.trials/stop)` | `POST /v1/{name}:stop`  
Stops a Trial. |
| `[suggest](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.studies.trials/suggest)` | `POST /v1/{parent}/trials:suggest`  
Adds one or more Trials to a Study, with parameter values suggested by Vertex AI Vizier. |

## REST Resource: [v1.projects.locations.tensorboards](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards)

 | Methods |
| --- |
| `[batchRead](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards/batchRead)` | `GET /v1/{tensorboard}:batchRead`  
Reads multiple TensorboardTimeSeries' data. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards/create)` | `POST /v1/{parent}/tensorboards`  
Creates a Tensorboard. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards/delete)` | `DELETE /v1/{name}`  
Deletes a Tensorboard. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards/get)` | `GET /v1/{name}`  
Gets a Tensorboard. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards/list)` | `GET /v1/{parent}/tensorboards`  
Lists Tensorboards in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards/patch)` | `PATCH /v1/{tensorboard.name}`  
Updates a Tensorboard. |
| `[readSize](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards/readSize)` | `GET /v1/{tensorboard}:readSize`  
Returns the storage size for a given TensorBoard instance. |
| `[readUsage](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards/readUsage)` | `GET /v1/{tensorboard}:readUsage`  
Returns a list of monthly active users for a given TensorBoard instance. |

## REST Resource: [v1.projects.locations.tensorboards.experiments](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments)

 | Methods |
| --- |
| `[batchCreate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments/batchCreate)` | `POST /v1/{parent}:batchCreate`  
Batch create TensorboardTimeSeries that belong to a TensorboardExperiment. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments/create)` | `POST /v1/{parent}/experiments`  
Creates a TensorboardExperiment. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments/delete)` | `DELETE /v1/{name}`  
Deletes a TensorboardExperiment. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments/get)` | `GET /v1/{name}`  
Gets a TensorboardExperiment. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments/list)` | `GET /v1/{parent}/experiments`  
Lists TensorboardExperiments in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments/patch)` | `PATCH /v1/{tensorboardExperiment.name}`  
Updates a TensorboardExperiment. |
| `[write](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments/write)` | `POST /v1/{tensorboardExperiment}:write`  
Write time series data points of multiple TensorboardTimeSeries in multiple TensorboardRun's. |

## REST Resource: [v1.projects.locations.tensorboards.experiments.runs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs)

 | Methods |
| --- |
| `[batchCreate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs/batchCreate)` | `POST /v1/{parent}/runs:batchCreate`  
Batch create TensorboardRuns. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs/create)` | `POST /v1/{parent}/runs`  
Creates a TensorboardRun. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs/delete)` | `DELETE /v1/{name}`  
Deletes a TensorboardRun. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs/get)` | `GET /v1/{name}`  
Gets a TensorboardRun. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs/list)` | `GET /v1/{parent}/runs`  
Lists TensorboardRuns in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs/patch)` | `PATCH /v1/{tensorboardRun.name}`  
Updates a TensorboardRun. |
| `[write](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs/write)` | `POST /v1/{tensorboardRun}:write`  
Write time series data points into multiple TensorboardTimeSeries under a TensorboardRun. |

## REST Resource: [v1.projects.locations.tensorboards.experiments.runs.timeSeries](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs.timeSeries)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs.timeSeries/create)` | `POST /v1/{parent}/timeSeries`  
Creates a TensorboardTimeSeries. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs.timeSeries/delete)` | `DELETE /v1/{name}`  
Deletes a TensorboardTimeSeries. |
| `[exportTensorboardTimeSeries](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs.timeSeries/exportTensorboardTimeSeries)` | `POST /v1/{tensorboardTimeSeries}:exportTensorboardTimeSeries`  
Exports a TensorboardTimeSeries' data. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs.timeSeries/get)` | `GET /v1/{name}`  
Gets a TensorboardTimeSeries. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs.timeSeries/list)` | `GET /v1/{parent}/timeSeries`  
Lists TensorboardTimeSeries in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs.timeSeries/patch)` | `PATCH /v1/{tensorboardTimeSeries.name}`  
Updates a TensorboardTimeSeries. |
| `[read](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs.timeSeries/read)` | `GET /v1/{tensorboardTimeSeries}:read`  
Reads a TensorboardTimeSeries' data. |
| `[readBlobData](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tensorboards.experiments.runs.timeSeries/readBlobData)` | `GET /v1/{timeSeries}:readBlobData`  
Gets bytes of TensorboardBlobs. |

## REST Resource: [v1.projects.locations.trainingPipelines](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.trainingPipelines)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.trainingPipelines/cancel)` | `POST /v1/{name}:cancel`  
Cancels a TrainingPipeline. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.trainingPipelines/create)` | `POST /v1/{parent}/trainingPipelines`  
Creates a TrainingPipeline. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.trainingPipelines/delete)` | `DELETE /v1/{name}`  
Deletes a TrainingPipeline. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.trainingPipelines/get)` | `GET /v1/{name}`  
Gets a TrainingPipeline. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.trainingPipelines/list)` | `GET /v1/{parent}/trainingPipelines`  
Lists TrainingPipelines in a Location. |

## REST Resource: [v1.projects.locations.tuningJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tuningJobs)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tuningJobs/cancel)` | `POST /v1/{name}:cancel`  
Cancels a tuning job. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tuningJobs/create)` | `POST /v1/{parent}/tuningJobs`  
Creates a tuning job. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tuningJobs/get)` | `GET /v1/{name}`  
Gets a tuning job. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tuningJobs/list)` | `GET /v1/{parent}/tuningJobs`  
Lists tuning jobs in a location. |
| `[rebaseTunedModel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.tuningJobs/rebaseTunedModel)` | `POST /v1/{parent}/tuningJobs:rebaseTunedModel`  
Rebase a tuned model. |

## REST Resource: [v1.publishers.models](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/publishers.models)

 | Methods |
| --- |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1/publishers.models/get)` | `GET /v1/{name}`  
Gets a Model Garden publisher model. |

 | Methods |
| --- |
| `[upload](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/media/upload)` | `POST /v1beta1/{parent}/ragFiles:upload`  
`POST /upload/v1beta1/{parent}/ragFiles:upload`  
Upload a file into a RagCorpus. |

## REST Resource: [v1beta1.operations](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/operations)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/operations/cancel)` | `POST /v1beta1/{name}:cancel`  
Starts asynchronous cancellation on a long-running operation. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/operations/delete)` | `DELETE /v1beta1/{name}`  
Deletes a long-running operation. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/operations/get)` | `GET /v1beta1/{name}`  
Gets the latest state of a long-running operation. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/operations/list)` | `GET /v1beta1/operations`  
Lists operations that match the specified filter in the request. |
| `[wait](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/operations/wait)` | `POST /v1beta1/{name}:wait`  
Waits until the specified long-running operation is done or reaches at most a specified timeout, returning the latest state. |

## REST Resource: [v1beta1.projects](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects)

 | Methods |
| --- |
| `[fetchPublisherModelConfig](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects/fetchPublisherModelConfig)` | `GET /v1beta1/{name}:fetchPublisherModelConfig`  
Fetches the configs of publisher models. |
| `[setPublisherModelConfig](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects/setPublisherModelConfig)` | `POST /v1beta1/{name}:setPublisherModelConfig`  
Sets (creates or updates) configs of publisher models. |

## REST Resource: [v1beta1.projects.locations](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations)

 | Methods |
| --- |
| `[askContexts](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/askContexts)` | `POST /v1beta1/{parent}:askContexts`  
Agentic Retrieval Ask API for RAG. |
| `[asyncRetrieveContexts](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/asyncRetrieveContexts)` | `POST /v1beta1/{parent}:asyncRetrieveContexts`  
Asynchronous API to retrieves relevant contexts for a query. |
| `[augmentPrompt](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/augmentPrompt)` | `POST /v1beta1/{parent}:augmentPrompt`  
Given an input prompt, it returns augmented prompt from vertex rag store to guide LLM towards generating grounded responses. |
| `[corroborateContent](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/corroborateContent)` | `POST /v1beta1/{parent}:corroborateContent`  
Given an input text, it returns a score that evaluates the factuality of the text. |
| `[deploy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/deploy)` | `POST /v1beta1/{destination}:deploy`  
Deploys a model to a new endpoint. |
| `[deployPublisherModel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/deployPublisherModel)   **(deprecated)**` | `POST /v1beta1/{destination}:deployPublisherModel`  
Deploys publisher models. |
| `[evaluateDataset](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/evaluateDataset)` | `POST /v1beta1/{location}:evaluateDataset`  
Evaluates a dataset based on a set of given metrics. |
| `[evaluateInstances](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/evaluateInstances)` | `POST /v1beta1/{location}:evaluateInstances`  
Evaluates instances based on a given metric. |
| `[generateSyntheticData](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/generateSyntheticData)` | `POST /v1beta1/{location}:generateSyntheticData`  
Generates synthetic (artificial) data based on a description |
| `[getRagEngineConfig](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/getRagEngineConfig)` | `GET /v1beta1/{name}`  
Gets a RagEngineConfig. |
| `[recommendSpec](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/recommendSpec)` | `POST /v1beta1/{parent}:recommendSpec`  
Gets a Model's spec recommendations. |
| `[retrieveContexts](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/retrieveContexts)` | `POST /v1beta1/{parent}:retrieveContexts`  
Retrieves relevant contexts for a query. |
| `[updateRagEngineConfig](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/updateRagEngineConfig)` | `PATCH /v1beta1/{ragEngineConfig.name}`  
Updates a RagEngineConfig. |

## REST Resource: [v1beta1.projects.locations.batchPredictionJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.batchPredictionJobs)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.batchPredictionJobs/cancel)` | `POST /v1beta1/{name}:cancel`  
Cancels a BatchPredictionJob. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.batchPredictionJobs/create)` | `POST /v1beta1/{parent}/batchPredictionJobs`  
Creates a BatchPredictionJob. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.batchPredictionJobs/delete)` | `DELETE /v1beta1/{name}`  
Deletes a BatchPredictionJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.batchPredictionJobs/get)` | `GET /v1beta1/{name}`  
Gets a BatchPredictionJob |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.batchPredictionJobs/list)` | `GET /v1beta1/{parent}/batchPredictionJobs`  
Lists BatchPredictionJobs in a Location. |

## REST Resource: [v1beta1.projects.locations.cachedContents](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.cachedContents)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.cachedContents/create)` | `POST /v1beta1/{parent}/cachedContents`  
Creates cached content, this call will initialize the cached content in the data storage, and users need to pay for the cache data storage. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.cachedContents/delete)` | `DELETE /v1beta1/{name}`  
Deletes cached content |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.cachedContents/get)` | `GET /v1beta1/{name}`  
Gets cached content configurations |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.cachedContents/list)` | `GET /v1beta1/{parent}/cachedContents`  
Lists cached contents in a project |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.cachedContents/patch)` | `PATCH /v1beta1/{cachedContent.name}`  
Updates cached content configurations |

## REST Resource: [v1beta1.projects.locations.customJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.customJobs)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.customJobs/cancel)` | `POST /v1beta1/{name}:cancel`  
Cancels a CustomJob. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.customJobs/create)` | `POST /v1beta1/{parent}/customJobs`  
Creates a CustomJob. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.customJobs/delete)` | `DELETE /v1beta1/{name}`  
Deletes a CustomJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.customJobs/get)` | `GET /v1beta1/{name}`  
Gets a CustomJob. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.customJobs/list)` | `GET /v1beta1/{parent}/customJobs`  
Lists CustomJobs in a Location. |

## REST Resource: [v1beta1.projects.locations.datasets](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets)

 | Methods |
| --- |
| `[assemble](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets/assemble)` | `POST /v1beta1/{name}:assemble`  
Assembles each row of a multimodal dataset and writes the result into a BigQuery table. |
| `[assess](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets/assess)` | `POST /v1beta1/{name}:assess`  
Assesses the state or validity of the dataset with respect to a given use case. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets/create)` | `POST /v1beta1/{parent}/datasets`  
Creates a Dataset. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets/delete)` | `DELETE /v1beta1/{name}`  
Deletes a Dataset. |
| `[export](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets/export)` | `POST /v1beta1/{name}:export`  
Exports data from a Dataset. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets/get)` | `GET /v1beta1/{name}`  
Gets a Dataset. |
| `[import](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets/import)` | `POST /v1beta1/{name}:import`  
Imports data into a Dataset. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets/list)` | `GET /v1beta1/{parent}/datasets`  
Lists Datasets in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets/patch)` | `PATCH /v1beta1/{dataset.name}`  
Updates a Dataset. |
| `[searchDataItems](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets/searchDataItems)` | `GET /v1beta1/{dataset}:searchDataItems`  
Searches DataItems in a Dataset. |

## REST Resource: [v1beta1.projects.locations.datasets.annotationSpecs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.annotationSpecs)

 | Methods |
| --- |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.annotationSpecs/get)` | `GET /v1beta1/{name}`  
Gets an AnnotationSpec. |

## REST Resource: [v1beta1.projects.locations.datasets.dataItems](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.dataItems)

 | Methods |
| --- |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.dataItems/list)` | `GET /v1beta1/{parent}/dataItems`  
Lists DataItems in a Dataset. |

## REST Resource: [v1beta1.projects.locations.datasets.dataItems.annotations](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.dataItems.annotations)

 | Methods |
| --- |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.dataItems.annotations/list)` | `GET /v1beta1/{parent}/annotations`  
Lists Annotations belongs to a dataitem. |

## REST Resource: [v1beta1.projects.locations.datasets.datasetVersions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.datasetVersions)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.datasetVersions/create)` | `POST /v1beta1/{parent}/datasetVersions`  
Create a version from a Dataset. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.datasetVersions/delete)` | `DELETE /v1beta1/{name}`  
Deletes a Dataset version. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.datasetVersions/get)` | `GET /v1beta1/{name}`  
Gets a Dataset version. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.datasetVersions/list)` | `GET /v1beta1/{parent}/datasetVersions`  
Lists DatasetVersions in a Dataset. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.datasetVersions/patch)` | `PATCH /v1beta1/{datasetVersion.name}`  
Updates a DatasetVersion. |
| `[restore](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.datasetVersions/restore)` | `GET /v1beta1/{name}:restore`  
Restores a dataset version. |

## REST Resource: [v1beta1.projects.locations.datasets.savedQueries](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.savedQueries)

 | Methods |
| --- |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.savedQueries/delete)` | `DELETE /v1beta1/{name}`  
Deletes a SavedQuery. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.datasets.savedQueries/list)` | `GET /v1beta1/{parent}/savedQueries`  
Lists SavedQueries in a Dataset. |

## REST Resource: [v1beta1.projects.locations.deploymentResourcePools](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.deploymentResourcePools)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.deploymentResourcePools/create)` | `POST /v1beta1/{parent}/deploymentResourcePools`  
Create a DeploymentResourcePool. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.deploymentResourcePools/delete)` | `DELETE /v1beta1/{name}`  
Delete a DeploymentResourcePool. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.deploymentResourcePools/get)` | `GET /v1beta1/{name}`  
Get a DeploymentResourcePool. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.deploymentResourcePools/list)` | `GET /v1beta1/{parent}/deploymentResourcePools`  
List DeploymentResourcePools in a location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.deploymentResourcePools/patch)` | `PATCH /v1beta1/{deploymentResourcePool.name}`  
Update a DeploymentResourcePool. |
| `[queryDeployedModels](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.deploymentResourcePools/queryDeployedModels)` | `GET /v1beta1/{deploymentResourcePool}:queryDeployedModels`  
List DeployedModels that have been deployed on this DeploymentResourcePool. |

## REST Resource: [v1beta1.projects.locations.endpoints](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints)

 | Methods |
| --- |
| `[countTokens](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/countTokens)` | `POST /v1beta1/{endpoint}:countTokens`  
Perform a token counting. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/create)` | `POST /v1beta1/{parent}/endpoints`  
Creates an Endpoint. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/delete)` | `DELETE /v1beta1/{name}`  
Deletes an Endpoint. |
| `[deployModel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/deployModel)` | `POST /v1beta1/{endpoint}:deployModel`  
Deploys a Model into this Endpoint, creating a DeployedModel within it. |
| `[directPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/directPredict)` | `POST /v1beta1/{endpoint}:directPredict`  
Perform an unary online prediction request to a gRPC model server for Vertex first-party products and frameworks. |
| `[directRawPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/directRawPredict)` | `POST /v1beta1/{endpoint}:directRawPredict`  
Perform an unary online prediction request to a gRPC model server for custom containers. |
| `[explain](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/explain)` | `POST /v1beta1/{endpoint}:explain`  
Perform an online explanation. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/get)` | `GET /v1beta1/{name}`  
Gets an Endpoint. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/getIamPolicy)` | `POST /v1beta1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/list)` | `GET /v1beta1/{parent}/endpoints`  
Lists Endpoints in a Location. |
| `[mutateDeployedModel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/mutateDeployedModel)` | `POST /v1beta1/{endpoint}:mutateDeployedModel`  
Updates an existing deployed model. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/patch)` | `PATCH /v1beta1/{endpoint.name}`  
Updates an Endpoint. |
| `[predict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/predict)` | `POST /v1beta1/{endpoint}:predict`  
Perform an online prediction. |
| `[predictLongRunning](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/predictLongRunning)` | `POST /v1beta1/{endpoint}:predictLongRunning` |
| `[rawPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/rawPredict)` | `POST /v1beta1/{endpoint}:rawPredict`  
Perform an online prediction with an arbitrary HTTP payload. |
| `[serverStreamingPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/serverStreamingPredict)` | `POST /v1beta1/{endpoint}:serverStreamingPredict`  
Perform a server-side streaming online prediction request for Vertex LLM streaming. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/setIamPolicy)` | `POST /v1beta1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[streamRawPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/streamRawPredict)` | `POST /v1beta1/{endpoint}:streamRawPredict`  
Perform a streaming online prediction with an arbitrary HTTP payload. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/testIamPermissions)` | `POST /v1beta1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |
| `[undeployModel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/undeployModel)` | `POST /v1beta1/{endpoint}:undeployModel`  
Undeploys a Model from an Endpoint, removing a DeployedModel from it, and freeing all resources it's using. |
| `[update](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints/update)` | `POST /v1beta1/{endpoint.name}:update`  
Updates an Endpoint with a long running operation. |

## REST Resource: [v1beta1.projects.locations.endpoints.chat](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints.chat)

 | Methods |
| --- |
| `[completions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.endpoints.chat/completions)` | `POST /v1beta1/{endpoint}/chat/completions`  
Exposes an OpenAI-compatible endpoint for chat completions. |

## REST Resource: [v1beta1.projects.locations.exampleStores](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.exampleStores)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.exampleStores/create)` | `POST /v1beta1/{parent}/exampleStores`  
Create an ExampleStore. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.exampleStores/delete)` | `DELETE /v1beta1/{name}`  
Delete an ExampleStore. |
| `[fetchExamples](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.exampleStores/fetchExamples)` | `POST /v1beta1/{exampleStore}:fetchExamples`  
Get Examples from the Example Store. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.exampleStores/get)` | `GET /v1beta1/{name}`  
Get an ExampleStore. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.exampleStores/list)` | `GET /v1beta1/{parent}/exampleStores`  
List ExampleStores in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.exampleStores/patch)` | `PATCH /v1beta1/{exampleStore.name}`  
Update an ExampleStore. |
| `[removeExamples](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.exampleStores/removeExamples)` | `POST /v1beta1/{exampleStore}:removeExamples`  
Remove Examples from the Example Store. |
| `[searchExamples](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.exampleStores/searchExamples)` | `POST /v1beta1/{exampleStore}:searchExamples`  
Search for similar Examples for given selection criteria. |
| `[upsertExamples](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.exampleStores/upsertExamples)` | `POST /v1beta1/{exampleStore}:upsertExamples`  
Create or update Examples in the Example Store. |

## REST Resource: [v1beta1.projects.locations.extensions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.extensions)

 | Methods |
| --- |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.extensions/delete)` | `DELETE /v1beta1/{name}`  
Deletes an Extension. |
| `[execute](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.extensions/execute)` | `POST /v1beta1/{name}:execute`  
Executes the request against a given extension. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.extensions/get)` | `GET /v1beta1/{name}`  
Gets an Extension. |
| `[import](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.extensions/import)` | `POST /v1beta1/{parent}/extensions:import`  
Imports an Extension. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.extensions/list)` | `GET /v1beta1/{parent}/extensions`  
Lists Extensions in a location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.extensions/patch)` | `PATCH /v1beta1/{extension.name}`  
Updates an Extension. |
| `[query](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.extensions/query)` | `POST /v1beta1/{name}:query`  
Queries an extension with a default controller. |

## REST Resource: [v1beta1.projects.locations.featureGroups](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups/create)` | `POST /v1beta1/{parent}/featureGroups`  
Creates a new FeatureGroup in a given project and location. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups/delete)` | `DELETE /v1beta1/{name}`  
Deletes a single FeatureGroup. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups/get)` | `GET /v1beta1/{name}`  
Gets details of a single FeatureGroup. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups/getIamPolicy)` | `POST /v1beta1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups/list)` | `GET /v1beta1/{parent}/featureGroups`  
Lists FeatureGroups in a given project and location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups/patch)` | `PATCH /v1beta1/{featureGroup.name}`  
Updates the parameters of a single FeatureGroup. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups/setIamPolicy)` | `POST /v1beta1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups/testIamPermissions)` | `POST /v1beta1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |

## REST Resource: [v1beta1.projects.locations.featureGroups.featureMonitors](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.featureMonitors)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.featureMonitors/create)` | `POST /v1beta1/{parent}/featureMonitors`  
Creates a new FeatureMonitor in a given project, location and FeatureGroup. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.featureMonitors/delete)` | `DELETE /v1beta1/{name}`  
Deletes a single FeatureMonitor. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.featureMonitors/get)` | `GET /v1beta1/{name}`  
Gets details of a single FeatureMonitor. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.featureMonitors/list)` | `GET /v1beta1/{parent}/featureMonitors`  
Lists FeatureGroups in a given project and location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.featureMonitors/patch)` | `PATCH /v1beta1/{featureMonitor.name}`  
Updates the parameters of a single FeatureMonitor. |

## REST Resource: [v1beta1.projects.locations.featureGroups.featureMonitors.featureMonitorJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.featureMonitors.featureMonitorJobs)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.featureMonitors.featureMonitorJobs/create)` | `POST /v1beta1/{parent}/featureMonitorJobs`  
Creates a new feature monitor job. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.featureMonitors.featureMonitorJobs/get)` | `GET /v1beta1/{name}`  
Get a feature monitor job. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.featureMonitors.featureMonitorJobs/list)` | `GET /v1beta1/{parent}/featureMonitorJobs`  
List feature monitor jobs. |

## REST Resource: [v1beta1.projects.locations.featureGroups.features](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.features)

 | Methods |
| --- |
| `[batchCreate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.features/batchCreate)` | `POST /v1beta1/{parent}/features:batchCreate`  
Creates a batch of Features in a given FeatureGroup. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.features/create)` | `POST /v1beta1/{parent}/features`  
Creates a new Feature in a given FeatureGroup. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.features/delete)` | `DELETE /v1beta1/{name}`  
Deletes a single Feature. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.features/get)` | `GET /v1beta1/{name}`  
Gets details of a single Feature. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.features/list)` | `GET /v1beta1/{parent}/features`  
Lists Features in a given FeatureGroup. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureGroups.features/patch)` | `PATCH /v1beta1/{feature.name}`  
Updates the parameters of a single Feature. |

## REST Resource: [v1beta1.projects.locations.featureOnlineStores](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores/create)` | `POST /v1beta1/{parent}/featureOnlineStores`  
Creates a new FeatureOnlineStore in a given project and location. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores/delete)` | `DELETE /v1beta1/{name}`  
Deletes a single FeatureOnlineStore. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores/get)` | `GET /v1beta1/{name}`  
Gets details of a single FeatureOnlineStore. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores/getIamPolicy)` | `POST /v1beta1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores/list)` | `GET /v1beta1/{parent}/featureOnlineStores`  
Lists FeatureOnlineStores in a given project and location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores/patch)` | `PATCH /v1beta1/{featureOnlineStore.name}`  
Updates the parameters of a single FeatureOnlineStore. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores/setIamPolicy)` | `POST /v1beta1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores/testIamPermissions)` | `POST /v1beta1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |

## REST Resource: [v1beta1.projects.locations.featureOnlineStores.featureViews](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/create)` | `POST /v1beta1/{parent}/featureViews`  
Creates a new FeatureView in a given FeatureOnlineStore. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/delete)` | `DELETE /v1beta1/{name}`  
Deletes a single FeatureView. |
| `[directWrite](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/directWrite)` | `POST /v1beta1/{featureView}:directWrite`  
Bidirectional streaming RPC to directly write to feature values in a feature view. |
| `[fetchFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/fetchFeatureValues)` | `POST /v1beta1/{featureView}:fetchFeatureValues`  
Fetch feature values under a FeatureView. |
| `[generateFetchAccessToken](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/generateFetchAccessToken)` | `POST /v1beta1/{featureView}:generateFetchAccessToken`  
RPC to generate an access token for the given feature view. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/get)` | `GET /v1beta1/{name}`  
Gets details of a single FeatureView. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/getIamPolicy)` | `POST /v1beta1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/list)` | `GET /v1beta1/{parent}/featureViews`  
Lists FeatureViews in a given FeatureOnlineStore. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/patch)` | `PATCH /v1beta1/{featureView.name}`  
Updates the parameters of a single FeatureView. |
| `[searchNearestEntities](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/searchNearestEntities)` | `POST /v1beta1/{featureView}:searchNearestEntities`  
Search the nearest entities under a FeatureView. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/setIamPolicy)` | `POST /v1beta1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[streamingFetchFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/streamingFetchFeatureValues)` | `POST /v1beta1/{featureView}:streamingFetchFeatureValues`  
Bidirectional streaming RPC to fetch feature values under a FeatureView. |
| `[sync](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/sync)` | `POST /v1beta1/{featureView}:sync`  
Triggers on-demand sync for the FeatureView. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews/testIamPermissions)` | `POST /v1beta1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |

## REST Resource: [v1beta1.projects.locations.featureOnlineStores.featureViews.featureViewSyncs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews.featureViewSyncs)

 | Methods |
| --- |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews.featureViewSyncs/get)` | `GET /v1beta1/{name}`  
Gets details of a single FeatureViewSync. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featureOnlineStores.featureViews.featureViewSyncs/list)` | `GET /v1beta1/{parent}/featureViewSyncs`  
Lists FeatureViewSyncs in a given FeatureView. |

## REST Resource: [v1beta1.projects.locations.featurestores](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores)

 | Methods |
| --- |
| `[batchReadFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores/batchReadFeatureValues)` | `POST /v1beta1/{featurestore}:batchReadFeatureValues`  
Batch reads Feature values from a Featurestore. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores/create)` | `POST /v1beta1/{parent}/featurestores`  
Creates a new Featurestore in a given project and location. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores/delete)` | `DELETE /v1beta1/{name}`  
Deletes a single Featurestore. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores/get)` | `GET /v1beta1/{name}`  
Gets details of a single Featurestore. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores/getIamPolicy)` | `POST /v1beta1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores/list)` | `GET /v1beta1/{parent}/featurestores`  
Lists Featurestores in a given project and location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores/patch)` | `PATCH /v1beta1/{featurestore.name}`  
Updates the parameters of a single Featurestore. |
| `[searchFeatures](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores/searchFeatures)` | `GET /v1beta1/{location}/featurestores:searchFeatures`  
Searches Features matching a query in a given project. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores/setIamPolicy)` | `POST /v1beta1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores/testIamPermissions)` | `POST /v1beta1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |

## REST Resource: [v1beta1.projects.locations.featurestores.entityTypes](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/create)` | `POST /v1beta1/{parent}/entityTypes`  
Creates a new EntityType in a given Featurestore. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/delete)` | `DELETE /v1beta1/{name}`  
Deletes a single EntityType. |
| `[deleteFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/deleteFeatureValues)` | `POST /v1beta1/{entityType}:deleteFeatureValues`  
Delete Feature values from Featurestore. |
| `[exportFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/exportFeatureValues)` | `POST /v1beta1/{entityType}:exportFeatureValues`  
Exports Feature values from all the entities of a target EntityType. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/get)` | `GET /v1beta1/{name}`  
Gets details of a single EntityType. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/getIamPolicy)` | `POST /v1beta1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[importFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/importFeatureValues)` | `POST /v1beta1/{entityType}:importFeatureValues`  
Imports Feature values into the Featurestore from a source storage. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/list)` | `GET /v1beta1/{parent}/entityTypes`  
Lists EntityTypes in a given Featurestore. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/patch)` | `PATCH /v1beta1/{entityType.name}`  
Updates the parameters of a single EntityType. |
| `[readFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/readFeatureValues)` | `POST /v1beta1/{entityType}:readFeatureValues`  
Reads Feature values of a specific entity of an EntityType. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/setIamPolicy)` | `POST /v1beta1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[streamingReadFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/streamingReadFeatureValues)` | `POST /v1beta1/{entityType}:streamingReadFeatureValues`  
Reads Feature values for multiple entities. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/testIamPermissions)` | `POST /v1beta1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |
| `[writeFeatureValues](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes/writeFeatureValues)` | `POST /v1beta1/{entityType}:writeFeatureValues`  
Writes Feature values of one or more entities of an EntityType. |

## REST Resource: [v1beta1.projects.locations.featurestores.entityTypes.features](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes.features)

 | Methods |
| --- |
| `[batchCreate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes.features/batchCreate)` | `POST /v1beta1/{parent}/features:batchCreate`  
Creates a batch of Features in a given EntityType. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes.features/create)` | `POST /v1beta1/{parent}/features`  
Creates a new Feature in a given EntityType. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes.features/delete)` | `DELETE /v1beta1/{name}`  
Deletes a single Feature. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes.features/get)` | `GET /v1beta1/{name}`  
Gets details of a single Feature. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes.features/list)` | `GET /v1beta1/{parent}/features`  
Lists Features in a given EntityType. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.featurestores.entityTypes.features/patch)` | `PATCH /v1beta1/{feature.name}`  
Updates the parameters of a single Feature. |

## REST Resource: [v1beta1.projects.locations.hyperparameterTuningJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.hyperparameterTuningJobs)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.hyperparameterTuningJobs/cancel)` | `POST /v1beta1/{name}:cancel`  
Cancels a HyperparameterTuningJob. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.hyperparameterTuningJobs/create)` | `POST /v1beta1/{parent}/hyperparameterTuningJobs`  
Creates a HyperparameterTuningJob |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.hyperparameterTuningJobs/delete)` | `DELETE /v1beta1/{name}`  
Deletes a HyperparameterTuningJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.hyperparameterTuningJobs/get)` | `GET /v1beta1/{name}`  
Gets a HyperparameterTuningJob |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.hyperparameterTuningJobs/list)` | `GET /v1beta1/{parent}/hyperparameterTuningJobs`  
Lists HyperparameterTuningJobs in a Location. |

## REST Resource: [v1beta1.projects.locations.indexEndpoints](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexEndpoints)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexEndpoints/create)` | `POST /v1beta1/{parent}/indexEndpoints`  
Creates an IndexEndpoint. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexEndpoints/delete)` | `DELETE /v1beta1/{name}`  
Deletes an IndexEndpoint. |
| `[deployIndex](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexEndpoints/deployIndex)` | `POST /v1beta1/{indexEndpoint}:deployIndex`  
Deploys an Index into this IndexEndpoint, creating a DeployedIndex within it. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexEndpoints/get)` | `GET /v1beta1/{name}`  
Gets an IndexEndpoint. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexEndpoints/list)` | `GET /v1beta1/{parent}/indexEndpoints`  
Lists IndexEndpoints in a Location. |
| `[mutateDeployedIndex](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexEndpoints/mutateDeployedIndex)` | `POST /v1beta1/{indexEndpoint}:mutateDeployedIndex`  
Update an existing DeployedIndex under an IndexEndpoint. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexEndpoints/patch)` | `PATCH /v1beta1/{indexEndpoint.name}`  
Updates an IndexEndpoint. |
| `[undeployIndex](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexEndpoints/undeployIndex)` | `POST /v1beta1/{indexEndpoint}:undeployIndex`  
Undeploys an Index from an IndexEndpoint, removing a DeployedIndex from it, and freeing all resources it's using. |

## REST Resource: [v1beta1.projects.locations.indexes](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexes)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexes/create)` | `POST /v1beta1/{parent}/indexes`  
Creates an Index. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexes/delete)` | `DELETE /v1beta1/{name}`  
Deletes an Index. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexes/get)` | `GET /v1beta1/{name}`  
Gets an Index. |
| `[import](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexes/import)` | `POST /v1beta1/{name}:import`  
Imports an Index from an external source (e.g., BigQuery). |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexes/list)` | `GET /v1beta1/{parent}/indexes`  
Lists Indexes in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexes/patch)` | `PATCH /v1beta1/{index.name}`  
Updates an Index. |
| `[removeDatapoints](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexes/removeDatapoints)` | `POST /v1beta1/{index}:removeDatapoints`  
Remove Datapoints from an Index. |
| `[upsertDatapoints](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.indexes/upsertDatapoints)` | `POST /v1beta1/{index}:upsertDatapoints`  
Add/update Datapoints into an Index. |

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores/create)` | `POST /v1beta1/{parent}/metadataStores`  
Initializes a MetadataStore, including allocation of resources. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores/delete)` | `DELETE /v1beta1/{name}`  
Deletes a single MetadataStore and all its child resources (Artifacts, Executions, and Contexts). |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores/get)` | `GET /v1beta1/{name}`  
Retrieves a specific MetadataStore. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores/list)` | `GET /v1beta1/{parent}/metadataStores`  
Lists MetadataStores for a Location. |

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.artifacts/create)` | `POST /v1beta1/{parent}/artifacts`  
Creates an Artifact associated with a MetadataStore. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.artifacts/delete)` | `DELETE /v1beta1/{name}`  
Deletes an Artifact. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.artifacts/get)` | `GET /v1beta1/{name}`  
Retrieves a specific Artifact. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.artifacts/list)` | `GET /v1beta1/{parent}/artifacts`  
Lists Artifacts in the MetadataStore. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.artifacts/patch)` | `PATCH /v1beta1/{artifact.name}`  
Updates a stored Artifact. |
| `[purge](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.artifacts/purge)` | `POST /v1beta1/{parent}/artifacts:purge`  
Purges Artifacts. |
| `[queryArtifactLineageSubgraph](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.artifacts/queryArtifactLineageSubgraph)` | `GET /v1beta1/{artifact}:queryArtifactLineageSubgraph`  
Retrieves lineage of an Artifact represented through Artifacts and Executions connected by Event edges and returned as a LineageSubgraph. |

## REST Resource: [v1beta1.projects.locations.metadataStores.contexts](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.contexts)

 | Methods |
| --- |
| `[addContextArtifactsAndExecutions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.contexts/addContextArtifactsAndExecutions)` | `POST /v1beta1/{context}:addContextArtifactsAndExecutions`  
Adds a set of Artifacts and Executions to a Context. |
| `[addContextChildren](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.contexts/addContextChildren)` | `POST /v1beta1/{context}:addContextChildren`  
Adds a set of Contexts as children to a parent Context. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.contexts/create)` | `POST /v1beta1/{parent}/contexts`  
Creates a Context associated with a MetadataStore. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.contexts/delete)` | `DELETE /v1beta1/{name}`  
Deletes a stored Context. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.contexts/get)` | `GET /v1beta1/{name}`  
Retrieves a specific Context. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.contexts/list)` | `GET /v1beta1/{parent}/contexts`  
Lists Contexts on the MetadataStore. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.contexts/patch)` | `PATCH /v1beta1/{context.name}`  
Updates a stored Context. |
| `[purge](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.contexts/purge)` | `POST /v1beta1/{parent}/contexts:purge`  
Purges Contexts. |
| `[queryContextLineageSubgraph](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.contexts/queryContextLineageSubgraph)` | `GET /v1beta1/{context}:queryContextLineageSubgraph`  
Retrieves Artifacts and Executions within the specified Context, connected by Event edges and returned as a LineageSubgraph. |
| `[removeContextChildren](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.contexts/removeContextChildren)` | `POST /v1beta1/{context}:removeContextChildren`  
Remove a set of children contexts from a parent Context. |

 | Methods |
| --- |
| `[addExecutionEvents](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.executions/addExecutionEvents)` | `POST /v1beta1/{execution}:addExecutionEvents`  
Adds Events to the specified Execution. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.executions/create)` | `POST /v1beta1/{parent}/executions`  
Creates an Execution associated with a MetadataStore. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.executions/delete)` | `DELETE /v1beta1/{name}`  
Deletes an Execution. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.executions/get)` | `GET /v1beta1/{name}`  
Retrieves a specific Execution. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.executions/list)` | `GET /v1beta1/{parent}/executions`  
Lists Executions in the MetadataStore. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.executions/patch)` | `PATCH /v1beta1/{execution.name}`  
Updates a stored Execution. |
| `[purge](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.executions/purge)` | `POST /v1beta1/{parent}/executions:purge`  
Purges Executions. |
| `[queryExecutionInputsAndOutputs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.executions/queryExecutionInputsAndOutputs)` | `GET /v1beta1/{execution}:queryExecutionInputsAndOutputs`  
Obtains the set of input and output Artifacts for this Execution, in the form of LineageSubgraph that also contains the Execution and connecting Events. |

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.metadataSchemas/create)` | `POST /v1beta1/{parent}/metadataSchemas`  
Creates a MetadataSchema. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.metadataSchemas/get)` | `GET /v1beta1/{name}`  
Retrieves a specific MetadataSchema. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.metadataStores.metadataSchemas/list)` | `GET /v1beta1/{parent}/metadataSchemas`  
Lists MetadataSchemas. |

## REST Resource: [v1beta1.projects.locations.migratableResources](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.migratableResources)

 | Methods |
| --- |
| `[batchMigrate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.migratableResources/batchMigrate)` | `POST /v1beta1/{parent}/migratableResources:batchMigrate`  
Batch migrates resources from ml.googleapis.com, automl.googleapis.com, and datalabeling.googleapis.com to Vertex AI. |
| `[search](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.migratableResources/search)` | `POST /v1beta1/{parent}/migratableResources:search`  
Searches all of the resources in automl.googleapis.com, datalabeling.googleapis.com and ml.googleapis.com that can be migrated to Vertex AI's given location. |

## REST Resource: [v1beta1.projects.locations.modelDeploymentMonitoringJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelDeploymentMonitoringJobs)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelDeploymentMonitoringJobs/create)` | `POST /v1beta1/{parent}/modelDeploymentMonitoringJobs`  
Creates a ModelDeploymentMonitoringJob. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelDeploymentMonitoringJobs/delete)` | `DELETE /v1beta1/{name}`  
Deletes a ModelDeploymentMonitoringJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelDeploymentMonitoringJobs/get)` | `GET /v1beta1/{name}`  
Gets a ModelDeploymentMonitoringJob. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelDeploymentMonitoringJobs/list)` | `GET /v1beta1/{parent}/modelDeploymentMonitoringJobs`  
Lists ModelDeploymentMonitoringJobs in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelDeploymentMonitoringJobs/patch)` | `PATCH /v1beta1/{modelDeploymentMonitoringJob.name}`  
Updates a ModelDeploymentMonitoringJob. |
| `[pause](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelDeploymentMonitoringJobs/pause)` | `POST /v1beta1/{name}:pause`  
Pauses a ModelDeploymentMonitoringJob. |
| `[resume](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelDeploymentMonitoringJobs/resume)` | `POST /v1beta1/{name}:resume`  
Resumes a paused ModelDeploymentMonitoringJob. |
| `[searchModelDeploymentMonitoringStatsAnomalies](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelDeploymentMonitoringJobs/searchModelDeploymentMonitoringStatsAnomalies)` | `POST /v1beta1/{modelDeploymentMonitoringJob}:searchModelDeploymentMonitoringStatsAnomalies`  
Searches Model Monitoring Statistics generated within a given time window. |

## REST Resource: [v1beta1.projects.locations.modelMonitors](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors/create)` | `POST /v1beta1/{parent}/modelMonitors`  
Creates a ModelMonitor. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors/delete)` | `DELETE /v1beta1/{name}`  
Deletes a ModelMonitor. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors/get)` | `GET /v1beta1/{name}`  
Gets a ModelMonitor. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors/list)` | `GET /v1beta1/{parent}/modelMonitors`  
Lists ModelMonitors in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors/patch)` | `PATCH /v1beta1/{modelMonitor.name}`  
Updates a ModelMonitor. |
| `[searchModelMonitoringAlerts](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors/searchModelMonitoringAlerts)` | `POST /v1beta1/{modelMonitor}:searchModelMonitoringAlerts`  
Returns the Model Monitoring alerts. |
| `[searchModelMonitoringStats](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors/searchModelMonitoringStats)` | `POST /v1beta1/{modelMonitor}:searchModelMonitoringStats`  
Searches Model Monitoring Stats generated within a given time window. |

## REST Resource: [v1beta1.projects.locations.modelMonitors.modelMonitoringJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors.modelMonitoringJobs)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors.modelMonitoringJobs/create)` | `POST /v1beta1/{parent}/modelMonitoringJobs`  
Creates a ModelMonitoringJob. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors.modelMonitoringJobs/delete)` | `DELETE /v1beta1/{name}`  
Deletes a ModelMonitoringJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors.modelMonitoringJobs/get)` | `GET /v1beta1/{name}`  
Gets a ModelMonitoringJob. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.modelMonitors.modelMonitoringJobs/list)` | `GET /v1beta1/{parent}/modelMonitoringJobs`  
Lists ModelMonitoringJobs. |

## REST Resource: [v1beta1.projects.locations.models](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models)

 | Methods |
| --- |
| `[copy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/copy)` | `POST /v1beta1/{parent}/models:copy`  
Copies an already existing Vertex AI Model into the specified Location. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/delete)` | `DELETE /v1beta1/{name}`  
Deletes a Model. |
| `[deleteVersion](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/deleteVersion)` | `DELETE /v1beta1/{name}:deleteVersion`  
Deletes a Model version. |
| `[export](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/export)` | `POST /v1beta1/{name}:export`  
Exports a trained, exportable Model to a location specified by the user. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/get)` | `GET /v1beta1/{name}`  
Gets a Model. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/getIamPolicy)` | `POST /v1beta1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/list)` | `GET /v1beta1/{parent}/models`  
Lists Models in a Location. |
| `[listCheckpoints](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/listCheckpoints)` | `GET /v1beta1/{name}:listCheckpoints`  
Lists checkpoints of the specified model version. |
| `[listVersions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/listVersions)` | `GET /v1beta1/{name}:listVersions`  
Lists versions of the specified model. |
| `[mergeVersionAliases](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/mergeVersionAliases)` | `POST /v1beta1/{name}:mergeVersionAliases`  
Merges a set of aliases for a Model version. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/patch)` | `PATCH /v1beta1/{model.name}`  
Updates a Model. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/setIamPolicy)` | `POST /v1beta1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/testIamPermissions)` | `POST /v1beta1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |
| `[updateExplanationDataset](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/updateExplanationDataset)` | `POST /v1beta1/{model}:updateExplanationDataset`  
Incrementally update the dataset used for an examples model. |
| `[upload](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models/upload)` | `POST /v1beta1/{parent}/models:upload`  
Uploads a Model artifact into Vertex AI. |

## REST Resource: [v1beta1.projects.locations.models.evaluations](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models.evaluations)

 | Methods |
| --- |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models.evaluations/get)` | `GET /v1beta1/{name}`  
Gets a ModelEvaluation. |
| `[import](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models.evaluations/import)` | `POST /v1beta1/{parent}/evaluations:import`  
Imports an externally generated ModelEvaluation. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models.evaluations/list)` | `GET /v1beta1/{parent}/evaluations`  
Lists ModelEvaluations in a Model. |

## REST Resource: [v1beta1.projects.locations.models.evaluations.slices](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models.evaluations.slices)

 | Methods |
| --- |
| `[batchImport](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models.evaluations.slices/batchImport)` | `POST /v1beta1/{parent}:batchImport`  
Imports a list of externally generated EvaluatedAnnotations. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models.evaluations.slices/get)` | `GET /v1beta1/{name}`  
Gets a ModelEvaluationSlice. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.models.evaluations.slices/list)` | `GET /v1beta1/{parent}/slices`  
Lists ModelEvaluationSlices in a ModelEvaluation. |

## REST Resource: [v1beta1.projects.locations.notebookExecutionJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookExecutionJobs)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookExecutionJobs/create)` | `POST /v1beta1/{parent}/notebookExecutionJobs`  
Creates a NotebookExecutionJob. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookExecutionJobs/delete)` | `DELETE /v1beta1/{name}`  
Deletes a NotebookExecutionJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookExecutionJobs/get)` | `GET /v1beta1/{name}`  
Gets a NotebookExecutionJob. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookExecutionJobs/list)` | `GET /v1beta1/{parent}/notebookExecutionJobs`  
Lists NotebookExecutionJobs in a Location. |

## REST Resource: [v1beta1.projects.locations.notebookRuntimeTemplates](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimeTemplates)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimeTemplates/create)` | `POST /v1beta1/{parent}/notebookRuntimeTemplates`  
Creates a NotebookRuntimeTemplate. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimeTemplates/delete)` | `DELETE /v1beta1/{name}`  
Deletes a NotebookRuntimeTemplate. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimeTemplates/get)` | `GET /v1beta1/{name}`  
Gets a NotebookRuntimeTemplate. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimeTemplates/getIamPolicy)` | `POST /v1beta1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimeTemplates/list)` | `GET /v1beta1/{parent}/notebookRuntimeTemplates`  
Lists NotebookRuntimeTemplates in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimeTemplates/patch)` | `PATCH /v1beta1/{notebookRuntimeTemplate.name}`  
Updates a NotebookRuntimeTemplate. |
| `[setIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimeTemplates/setIamPolicy)` | `POST /v1beta1/{resource}:setIamPolicy`  
Sets the access control policy on the specified resource. |
| `[testIamPermissions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimeTemplates/testIamPermissions)` | `POST /v1beta1/{resource}:testIamPermissions`  
Returns permissions that a caller has on the specified resource. |

## REST Resource: [v1beta1.projects.locations.notebookRuntimes](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimes)

 | Methods |
| --- |
| `[assign](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimes/assign)` | `POST /v1beta1/{parent}/notebookRuntimes:assign`  
Assigns a NotebookRuntime to a user for a particular Notebook file. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimes/delete)` | `DELETE /v1beta1/{name}`  
Deletes a NotebookRuntime. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimes/get)` | `GET /v1beta1/{name}`  
Gets a NotebookRuntime. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimes/list)` | `GET /v1beta1/{parent}/notebookRuntimes`  
Lists NotebookRuntimes in a Location. |
| `[start](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimes/start)` | `POST /v1beta1/{name}:start`  
Starts a NotebookRuntime. |
| `[stop](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimes/stop)` | `POST /v1beta1/{name}:stop`  
Stops a NotebookRuntime. |
| `[upgrade](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.notebookRuntimes/upgrade)` | `POST /v1beta1/{name}:upgrade`  
Upgrades a NotebookRuntime. |

## REST Resource: [v1beta1.projects.locations.operations](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.operations)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.operations/cancel)` | `POST /v1beta1/{name}:cancel`  
Starts asynchronous cancellation on a long-running operation. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.operations/delete)` | `DELETE /v1beta1/{name}`  
Deletes a long-running operation. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.operations/get)` | `GET /v1beta1/{name}`  
Gets the latest state of a long-running operation. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.operations/list)` | `GET /v1beta1/{name}/operations`  
Lists operations that match the specified filter in the request. |
| `[wait](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.operations/wait)` | `POST /v1beta1/{name}:wait`  
Waits until the specified long-running operation is done or reaches at most a specified timeout, returning the latest state. |

## REST Resource: [v1beta1.projects.locations.persistentResources](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.persistentResources)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.persistentResources/create)` | `POST /v1beta1/{parent}/persistentResources`  
Creates a PersistentResource. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.persistentResources/delete)` | `DELETE /v1beta1/{name}`  
Deletes a PersistentResource. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.persistentResources/get)` | `GET /v1beta1/{name}`  
Gets a PersistentResource. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.persistentResources/list)` | `GET /v1beta1/{parent}/persistentResources`  
Lists PersistentResources in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.persistentResources/patch)` | `PATCH /v1beta1/{persistentResource.name}`  
Updates a PersistentResource. |
| `[reboot](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.persistentResources/reboot)` | `POST /v1beta1/{name}:reboot`  
Reboots a PersistentResource. |

## REST Resource: [v1beta1.projects.locations.pipelineJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.pipelineJobs)

 | Methods |
| --- |
| `[batchCancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.pipelineJobs/batchCancel)` | `POST /v1beta1/{parent}/pipelineJobs:batchCancel`  
Batch cancel PipelineJobs. |
| `[batchDelete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.pipelineJobs/batchDelete)` | `POST /v1beta1/{parent}/pipelineJobs:batchDelete`  
Batch deletes PipelineJobs The Operation is atomic. |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.pipelineJobs/cancel)` | `POST /v1beta1/{name}:cancel`  
Cancels a PipelineJob. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.pipelineJobs/create)` | `POST /v1beta1/{parent}/pipelineJobs`  
Creates a PipelineJob. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.pipelineJobs/delete)` | `DELETE /v1beta1/{name}`  
Deletes a PipelineJob. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.pipelineJobs/get)` | `GET /v1beta1/{name}`  
Gets a PipelineJob. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.pipelineJobs/list)` | `GET /v1beta1/{parent}/pipelineJobs`  
Lists PipelineJobs in a Location. |

## REST Resource: [v1beta1.projects.locations.publishers.models](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models)

 | Methods |
| --- |
| `[countTokens](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models/countTokens)` | `POST /v1beta1/{endpoint}:countTokens`  
Perform a token counting. |
| `[embedContent](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models/embedContent)` | `POST /v1beta1/{model}:embedContent`  
Embed content with multimodal inputs. |
| `[export](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models/export)` | `POST /v1beta1/{parent}/{name}:export`  
Exports a publisher model to a user provided Google Cloud Storage bucket. |
| `[fetchPublisherModelConfig](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models/fetchPublisherModelConfig)` | `GET /v1beta1/{name}:fetchPublisherModelConfig`  
Fetches the configs of publisher models. |
| `[getIamPolicy](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models/getIamPolicy)` | `POST /v1beta1/{resource}:getIamPolicy`  
Gets the access control policy for a resource. |
| `[predict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models/predict)` | `POST /v1beta1/{endpoint}:predict`  
Perform an online prediction. |
| `[predictLongRunning](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models/predictLongRunning)` | `POST /v1beta1/{endpoint}:predictLongRunning` |
| `[rawPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models/rawPredict)` | `POST /v1beta1/{endpoint}:rawPredict`  
Perform an online prediction with an arbitrary HTTP payload. |
| `[serverStreamingPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models/serverStreamingPredict)` | `POST /v1beta1/{endpoint}:serverStreamingPredict`  
Perform a server-side streaming online prediction request for Vertex LLM streaming. |
| `[setPublisherModelConfig](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models/setPublisherModelConfig)` | `POST /v1beta1/{name}:setPublisherModelConfig`  
Sets (creates or updates) configs of publisher models. |
| `[streamRawPredict](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.publishers.models/streamRawPredict)` | `POST /v1beta1/{endpoint}:streamRawPredict`  
Perform a streaming online prediction with an arbitrary HTTP payload. |

## REST Resource: [v1beta1.projects.locations.ragCorpora](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora/create)` | `POST /v1beta1/{parent}/ragCorpora`  
Creates a RagCorpus. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora/delete)` | `DELETE /v1beta1/{name}`  
Deletes a RagCorpus. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora/get)` | `GET /v1beta1/{name}`  
Gets a RagCorpus. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora/list)` | `GET /v1beta1/{parent}/ragCorpora`  
Lists RagCorpora in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora/patch)` | `PATCH /v1beta1/{ragCorpus.name}`  
Updates a RagCorpus. |

## REST Resource: [v1beta1.projects.locations.ragCorpora.ragDataSchemas](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragDataSchemas)

 | Methods |
| --- |
| `[batchCreate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragDataSchemas/batchCreate)` | `POST /v1beta1/{parent}/ragDataSchemas:batchCreate`  
Batch Create one or more RagDataSchemas |
| `[batchDelete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragDataSchemas/batchDelete)` | `POST /v1beta1/{parent}/ragDataSchemas:batchDelete`  
Batch Deletes one or more RagDataSchemas |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragDataSchemas/create)` | `POST /v1beta1/{parent}/ragDataSchemas`  
Creates a RagDataSchema. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragDataSchemas/delete)` | `DELETE /v1beta1/{name}`  
Deletes a RagDataSchema. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragDataSchemas/get)` | `GET /v1beta1/{name}`  
Gets a RagDataSchema. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragDataSchemas/list)` | `GET /v1beta1/{parent}/ragDataSchemas`  
Lists RagDataSchemas in a Location. |

## REST Resource: [v1beta1.projects.locations.ragCorpora.ragFiles](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles)

 | Methods |
| --- |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles/delete)` | `DELETE /v1beta1/{name}`  
Deletes a RagFile. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles/get)` | `GET /v1beta1/{name}`  
Gets a RagFile. |
| `[import](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles/import)` | `POST /v1beta1/{parent}/ragFiles:import`  
Import files from Google Cloud Storage or Google Drive into a RagCorpus. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles/list)` | `GET /v1beta1/{parent}/ragFiles`  
Lists RagFiles in a RagCorpus. |

 | Methods |
| --- |
| `[batchCreate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles.ragMetadata/batchCreate)` | `POST /v1beta1/{parent}/ragMetadata:batchCreate`  
Batch Create one or more RagMetadatas |
| `[batchDelete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles.ragMetadata/batchDelete)` | `POST /v1beta1/{parent}/ragMetadata:batchDelete`  
Batch Deletes one or more RagMetadata. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles.ragMetadata/create)` | `POST /v1beta1/{parent}/ragMetadata`  
Creates a RagMetadata. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles.ragMetadata/delete)` | `DELETE /v1beta1/{name}`  
Deletes a RagMetadata. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles.ragMetadata/get)` | `GET /v1beta1/{name}`  
Gets a RagMetadata. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles.ragMetadata/list)` | `GET /v1beta1/{parent}/ragMetadata`  
Lists RagMetadata in a RagFile. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.ragCorpora.ragFiles.ragMetadata/patch)` | `PATCH /v1beta1/{ragMetadata.name}`  
Updates a RagMetadata. |

## REST Resource: [v1beta1.projects.locations.reasoningEngines](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines/create)` | `POST /v1beta1/{parent}/reasoningEngines`  
Creates a reasoning engine. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines/delete)` | `DELETE /v1beta1/{name}`  
Deletes a reasoning engine. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines/get)` | `GET /v1beta1/{name}`  
Gets a reasoning engine. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines/list)` | `GET /v1beta1/{parent}/reasoningEngines`  
Lists reasoning engines in a location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines/patch)` | `PATCH /v1beta1/{reasoningEngine.name}`  
Updates a reasoning engine. |
| `[query](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines/query)` | `POST /v1beta1/{name}:query`  
Queries using a reasoning engine. |
| `[streamQuery](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines/streamQuery)` | `POST /v1beta1/{name}:streamQuery`  
Streams queries using a reasoning engine. |

## REST Resource: [v1beta1.projects.locations.reasoningEngines.memories](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.memories)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.memories/create)` | `POST /v1beta1/{parent}/memories`  
Create a Memory. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.memories/delete)` | `DELETE /v1beta1/{name}`  
Delete a Memory. |
| `[generate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.memories/generate)` | `POST /v1beta1/{parent}/memories:generate`  
Generate memories. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.memories/get)` | `GET /v1beta1/{name}`  
Get a Memory. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.memories/list)` | `GET /v1beta1/{parent}/memories`  
List Memories. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.memories/patch)` | `PATCH /v1beta1/{memory.name}`  
Update a Memory. |
| `[retrieve](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.memories/retrieve)` | `POST /v1beta1/{parent}/memories:retrieve`  
Retrieve memories. |

## REST Resource: [v1beta1.projects.locations.reasoningEngines.sessions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions)

 | Methods |
| --- |
| `[appendEvent](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions/appendEvent)` | `POST /v1beta1/{name}:appendEvent`  
Appends an event to a given session. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions/create)` | `POST /v1beta1/{parent}/sessions`  
Creates a new `[Session](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions#Session)`. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions/delete)` | `DELETE /v1beta1/{name}`  
Deletes details of the specific `[Session](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions#Session)`. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions/get)` | `GET /v1beta1/{name}`  
Gets details of the specific `[Session](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions#Session)`. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions/list)` | `GET /v1beta1/{parent}/sessions`  
Lists `[Sessions](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions#Session)` in a given reasoning engine. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions/patch)` | `PATCH /v1beta1/{session.name}`  
Updates the specific `[Session](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions#Session)`. |

## REST Resource: [v1beta1.projects.locations.reasoningEngines.sessions.events](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions.events)

 | Methods |
| --- |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions.events/list)` | `GET /v1beta1/{parent}/events`  
Lists `[Events](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/Event)` in a given session. |

## REST Resource: [v1beta1.projects.locations.schedules](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.schedules)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.schedules/create)` | `POST /v1beta1/{parent}/schedules`  
Creates a Schedule. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.schedules/delete)` | `DELETE /v1beta1/{name}`  
Deletes a Schedule. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.schedules/get)` | `GET /v1beta1/{name}`  
Gets a Schedule. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.schedules/list)` | `GET /v1beta1/{parent}/schedules`  
Lists Schedules in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.schedules/patch)` | `PATCH /v1beta1/{schedule.name}`  
Updates an active or paused Schedule. |
| `[pause](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.schedules/pause)` | `POST /v1beta1/{name}:pause`  
Pauses a Schedule. |
| `[resume](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.schedules/resume)` | `POST /v1beta1/{name}:resume`  
Resumes a paused Schedule to start scheduling new runs. |

## REST Resource: [v1beta1.projects.locations.specialistPools](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.specialistPools)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.specialistPools/create)` | `POST /v1beta1/{parent}/specialistPools`  
Creates a SpecialistPool. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.specialistPools/delete)` | `DELETE /v1beta1/{name}`  
Deletes a SpecialistPool as well as all Specialists in the pool. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.specialistPools/get)` | `GET /v1beta1/{name}`  
Gets a SpecialistPool. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.specialistPools/list)` | `GET /v1beta1/{parent}/specialistPools`  
Lists SpecialistPools in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.specialistPools/patch)` | `PATCH /v1beta1/{specialistPool.name}`  
Updates a SpecialistPool. |

## REST Resource: [v1beta1.projects.locations.studies](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies/create)` | `POST /v1beta1/{parent}/studies`  
Creates a Study. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies/delete)` | `DELETE /v1beta1/{name}`  
Deletes a Study. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies/get)` | `GET /v1beta1/{name}`  
Gets a Study by name. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies/list)` | `GET /v1beta1/{parent}/studies`  
Lists all the studies in a region for an associated project. |
| `[lookup](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies/lookup)` | `POST /v1beta1/{parent}/studies:lookup`  
Looks a study up using the user-defined display\_name field instead of the fully qualified resource name. |

## REST Resource: [v1beta1.projects.locations.studies.trials](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies.trials)

 | Methods |
| --- |
| `[addTrialMeasurement](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies.trials/addTrialMeasurement)` | `POST /v1beta1/{trialName}:addTrialMeasurement`  
Adds a measurement of the objective metrics to a Trial. |
| `[checkTrialEarlyStoppingState](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies.trials/checkTrialEarlyStoppingState)` | `POST /v1beta1/{trialName}:checkTrialEarlyStoppingState`  
Checks whether a Trial should stop or not. |
| `[complete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies.trials/complete)` | `POST /v1beta1/{name}:complete`  
Marks a Trial as complete. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies.trials/create)` | `POST /v1beta1/{parent}/trials`  
Adds a user provided Trial to a Study. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies.trials/delete)` | `DELETE /v1beta1/{name}`  
Deletes a Trial. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies.trials/get)` | `GET /v1beta1/{name}`  
Gets a Trial. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies.trials/list)` | `GET /v1beta1/{parent}/trials`  
Lists the Trials associated with a Study. |
| `[listOptimalTrials](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies.trials/listOptimalTrials)` | `POST /v1beta1/{parent}/trials:listOptimalTrials`  
Lists the pareto-optimal Trials for multi-objective Study or the optimal Trials for single-objective Study. |
| `[stop](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies.trials/stop)` | `POST /v1beta1/{name}:stop`  
Stops a Trial. |
| `[suggest](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.studies.trials/suggest)` | `POST /v1beta1/{parent}/trials:suggest`  
Adds one or more Trials to a Study, with parameter values suggested by Vertex AI Vizier. |

## REST Resource: [v1beta1.projects.locations.tensorboards](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards)

 | Methods |
| --- |
| `[batchRead](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards/batchRead)` | `GET /v1beta1/{tensorboard}:batchRead`  
Reads multiple TensorboardTimeSeries' data. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards/create)` | `POST /v1beta1/{parent}/tensorboards`  
Creates a Tensorboard. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards/delete)` | `DELETE /v1beta1/{name}`  
Deletes a Tensorboard. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards/get)` | `GET /v1beta1/{name}`  
Gets a Tensorboard. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards/list)` | `GET /v1beta1/{parent}/tensorboards`  
Lists Tensorboards in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards/patch)` | `PATCH /v1beta1/{tensorboard.name}`  
Updates a Tensorboard. |
| `[readSize](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards/readSize)` | `GET /v1beta1/{tensorboard}:readSize`  
Returns the storage size for a given TensorBoard instance. |
| `[readUsage](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards/readUsage)` | `GET /v1beta1/{tensorboard}:readUsage`  
Returns a list of monthly active users for a given TensorBoard instance. |

## REST Resource: [v1beta1.projects.locations.tensorboards.experiments](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments)

 | Methods |
| --- |
| `[batchCreate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments/batchCreate)` | `POST /v1beta1/{parent}:batchCreate`  
Batch create TensorboardTimeSeries that belong to a TensorboardExperiment. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments/create)` | `POST /v1beta1/{parent}/experiments`  
Creates a TensorboardExperiment. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments/delete)` | `DELETE /v1beta1/{name}`  
Deletes a TensorboardExperiment. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments/get)` | `GET /v1beta1/{name}`  
Gets a TensorboardExperiment. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments/list)` | `GET /v1beta1/{parent}/experiments`  
Lists TensorboardExperiments in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments/patch)` | `PATCH /v1beta1/{tensorboardExperiment.name}`  
Updates a TensorboardExperiment. |
| `[write](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments/write)` | `POST /v1beta1/{tensorboardExperiment}:write`  
Write time series data points of multiple TensorboardTimeSeries in multiple TensorboardRun's. |

## REST Resource: [v1beta1.projects.locations.tensorboards.experiments.runs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs)

 | Methods |
| --- |
| `[batchCreate](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs/batchCreate)` | `POST /v1beta1/{parent}/runs:batchCreate`  
Batch create TensorboardRuns. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs/create)` | `POST /v1beta1/{parent}/runs`  
Creates a TensorboardRun. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs/delete)` | `DELETE /v1beta1/{name}`  
Deletes a TensorboardRun. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs/get)` | `GET /v1beta1/{name}`  
Gets a TensorboardRun. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs/list)` | `GET /v1beta1/{parent}/runs`  
Lists TensorboardRuns in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs/patch)` | `PATCH /v1beta1/{tensorboardRun.name}`  
Updates a TensorboardRun. |
| `[write](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs/write)` | `POST /v1beta1/{tensorboardRun}:write`  
Write time series data points into multiple TensorboardTimeSeries under a TensorboardRun. |

## REST Resource: [v1beta1.projects.locations.tensorboards.experiments.runs.timeSeries](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs.timeSeries)

 | Methods |
| --- |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs.timeSeries/create)` | `POST /v1beta1/{parent}/timeSeries`  
Creates a TensorboardTimeSeries. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs.timeSeries/delete)` | `DELETE /v1beta1/{name}`  
Deletes a TensorboardTimeSeries. |
| `[exportTensorboardTimeSeries](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs.timeSeries/exportTensorboardTimeSeries)` | `POST /v1beta1/{tensorboardTimeSeries}:exportTensorboardTimeSeries`  
Exports a TensorboardTimeSeries' data. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs.timeSeries/get)` | `GET /v1beta1/{name}`  
Gets a TensorboardTimeSeries. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs.timeSeries/list)` | `GET /v1beta1/{parent}/timeSeries`  
Lists TensorboardTimeSeries in a Location. |
| `[patch](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs.timeSeries/patch)` | `PATCH /v1beta1/{tensorboardTimeSeries.name}`  
Updates a TensorboardTimeSeries. |
| `[read](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs.timeSeries/read)` | `GET /v1beta1/{tensorboardTimeSeries}:read`  
Reads a TensorboardTimeSeries' data. |
| `[readBlobData](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tensorboards.experiments.runs.timeSeries/readBlobData)` | `GET /v1beta1/{timeSeries}:readBlobData`  
Gets bytes of TensorboardBlobs. |

## REST Resource: [v1beta1.projects.locations.trainingPipelines](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.trainingPipelines)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.trainingPipelines/cancel)` | `POST /v1beta1/{name}:cancel`  
Cancels a TrainingPipeline. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.trainingPipelines/create)` | `POST /v1beta1/{parent}/trainingPipelines`  
Creates a TrainingPipeline. |
| `[delete](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.trainingPipelines/delete)` | `DELETE /v1beta1/{name}`  
Deletes a TrainingPipeline. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.trainingPipelines/get)` | `GET /v1beta1/{name}`  
Gets a TrainingPipeline. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.trainingPipelines/list)` | `GET /v1beta1/{parent}/trainingPipelines`  
Lists TrainingPipelines in a Location. |

## REST Resource: [v1beta1.projects.locations.tuningJobs](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tuningJobs)

 | Methods |
| --- |
| `[cancel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tuningJobs/cancel)` | `POST /v1beta1/{name}:cancel`  
Cancels a tuning job. |
| `[create](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tuningJobs/create)` | `POST /v1beta1/{parent}/tuningJobs`  
Creates a tuning job. |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tuningJobs/get)` | `GET /v1beta1/{name}`  
Gets a tuning job. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tuningJobs/list)` | `GET /v1beta1/{parent}/tuningJobs`  
Lists tuning jobs in a location. |
| `[rebaseTunedModel](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations.tuningJobs/rebaseTunedModel)` | `POST /v1beta1/{parent}/tuningJobs:rebaseTunedModel`  
Rebase a tuned model. |

## REST Resource: [v1beta1.projects.modelGardenEula](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.modelGardenEula)

 | Methods |
| --- |
| `[accept](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.modelGardenEula/accept)` | `POST /v1beta1/{parent}/modelGardenEula:accept`  
Accepts the EULA acceptance status of a publisher model. |
| `[check](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.modelGardenEula/check)` | `POST /v1beta1/{parent}/modelGardenEula:check`  
Checks the EULA acceptance status of a publisher model. |

## REST Resource: [v1beta1.publishers.models](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/publishers.models)

 | Methods |
| --- |
| `[get](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/publishers.models/get)` | `GET /v1beta1/{name}`  
Gets a Model Garden publisher model. |
| `[list](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/publishers.models/list)` | `GET /v1beta1/{parent}/models`  
Lists publisher models in Model Garden. |

---
> **Note:** This page contains 2 cross-origin iframe(s) that could not be accessed due to browser security policies. Some content may be missing. Links to these iframes have been preserved where possible.


---
Source: [Vertex AI API  |  Google Cloud Documentation](https://docs.cloud.google.com/vertex-ai/docs/reference/rest?apix=true)