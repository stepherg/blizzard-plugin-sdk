#pragma once

#include <rbus.h>
#include "google/protobuf/any.pb-c.h"
#include "google/protobuf/empty.pb-c.h"
#include "description.pb-c.h"
#include "messages.pb-c.h"
#include "descriptor.pb-c.h"
#include "value.pb-c.h"

typedef struct {
   const rbusDataElement_t* rbus_elements;
   size_t rbus_element_count;
   Blizzard__Plugin__Description__PluginDescription* plugin_description;
} PluginRegistration;

// Signature of the registration function each plugin must export
typedef PluginRegistration* (*plugin_register_fn)(void);