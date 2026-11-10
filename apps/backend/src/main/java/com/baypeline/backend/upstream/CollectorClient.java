package com.baypeline.backend.upstream;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/** KYTCollectionRequest → KYTDataSnapshot. */
public interface CollectorClient {

    JsonNode collect(String requestId, ObjectNode collectionRequest);
}
