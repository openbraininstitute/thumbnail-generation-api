# Thumbnail Generation API

## Overview

The Thumbnail Generation API provides the service for generating thumbnails of morphologies/electrophysiologies and the soma of morphologies. The API is designed to receive the id of a resource (morphology or electrophysiology) available in [Entitycore](https://github.com/openbraininstitute/entitycore), and produce a corresponding thumbnail image.

## Install

To get started with the Thumbnail Generation API, follow these simple steps:

1. **Clone the repository:**
    ```sh
    git clone https://github.com/openbraininstitute/thumbnail-generation-api.git
    cd thumbnail-generation-api
    ```

2. **Install [Poetry](https://python-poetry.org/docs/)**

3. **Install the dependencies:**
    ```sh
    make install
    ```

4. **Run the application:**
    ```sh
    make dev
    ```

5. **Alternatively, run the application inside a Docker container:**
    ```sh
    make up
    ```


Your Thumbnail Generation API should now be running at `http://127.0.0.1:8003`.

## Examples

Here are some simple examples to get you started with using the Thumbnail Generation API:

1. **Generate a thumbnail for electrophysiologies:**
    ```sh
    AUTH_TOKEN=xxxxxxxx
    ENTITY_ID=bdba2c48-df47-4bd9-bbfe-e4ec2c6a5abe
    ASSET_ID=f111eab2-bc23-4a73-b8b2-c0592c02fe67
    curl -X GET "http://127.0.0.1:8003/core/electrical-cell-recording/preview?dpi=400&entity_id=$ENTITY_ID$&asset_id=$ASSET_ID" -H "accept: application/json" -H "Authorization: Bearer $AUTH_TOKEN"
    ```

2. **Generate a thumbnail for morphologies:**
    ```sh
    AUTH_TOKEN=xxxxxxxx
    ENTITY_ID=059bd4df-acc5-4ec3-8203-53ceacd0e2e0
    ASSET_ID=f11bc66c-68f3-4310-9e34-7b947a0c5be2
    curl -X GET "http://127.0.0.1:8003/core/reconstruction-morphology/preview?dpi=400&entity_id=$ENTITY_ID$&asset_id=$ASSET_ID" -H "accept: application/json" -H "Authorization: Bearer $AUTH_TOKEN"
    ```

For more detailed usage and examples, please refer to the documentation available at `http://127.0.0.1:8003/docs`.


## Testing

Tests can be run using the following command:

```
make test
```


## Acknowledgements

The development of this software was supported by funding to the Blue Brain Project, a research center of the École polytechnique fédérale de Lausanne (EPFL), from the Swiss government’s ETH Board of the Swiss Federal Institutes of Technology.

For license and authors, see LICENSE.txt and AUTHORS.txt respectively.

Copyright &copy; 2024 Blue Brain Project/EPFL

Copyright &copy; 2025 Open Brain Institute
