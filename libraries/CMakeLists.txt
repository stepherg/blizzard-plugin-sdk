cmake_minimum_required(VERSION 3.10)

project(blizzard_protobufs LANGUAGES C CXX)
include(ExternalProject)

# -------------------- Options --------------------
set(GENERATED_BASE "${CMAKE_CURRENT_BINARY_DIR}/src" CACHE PATH "Where to place generated sources")

set(C_OUT_DIR "${GENERATED_BASE}/c")

# -------------------- Dependencies --------------------
find_package(Git REQUIRED)
find_package(Protobuf REQUIRED)
find_library(PROTOBUF_C_LIBRARIES NAMES protobuf-c REQUIRED)
find_package(absl REQUIRED)

# protoc-gen-c is required for protobuf-c output
find_program(PROTOC_GEN_C protoc-gen-c)

if(NOT PROTOC_GEN_C)
   message(FATAL_ERROR "protoc-gen-c not found. Install protobuf-c compiler (e.g., brew install protobuf-c or apt install protobuf-c-compiler).")
endif()

# Standards & PIC
set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(APPLE)
   include_directories(/opt/homebrew/include)
   link_directories(/opt/homebrew/lib)
   set(CMAKE_INSTALL_RPATH "${CMAKE_INSTALL_PREFIX}/lib")
   set(CMAKE_BUILD_WITH_INSTALL_RPATH TRUE)
   set(CMAKE_INSTALL_RPATH_USE_LINK_PATH TRUE)
endif()

set(BLIZZARD_SRC "${SOURCE_DIR}")

# Blizzard proto roots
set(BLIZZARD_PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/proto")

# Ensure output dirs exist
file(MAKE_DIRECTORY "${C_OUT_DIR}")

# -------------------- Protobuf generation --------------------
set(PROTO_INCLUDES
   -I "${Protobuf_INCLUDE_DIRS}"
   -I "${BLIZZARD_PROTO_DIR}")

set(BLIZZARD_PROTOS
   "${BLIZZARD_PROTO_DIR}/messages.proto"
   "${BLIZZARD_PROTO_DIR}/description.proto"
   "${BLIZZARD_PROTO_DIR}/descriptor.proto"
   "${BLIZZARD_PROTO_DIR}/value.proto")

# ---- C (protobuf-c) outputs
set(GEN_C_SRCS
   "${C_OUT_DIR}/messages.pb-c.c"
   "${C_OUT_DIR}/description.pb-c.c"
   "${C_OUT_DIR}/descriptor.pb-c.c"
   "${C_OUT_DIR}/value.pb-c.c"
   "${C_OUT_DIR}/google/protobuf/any.pb-c.c"
   "${C_OUT_DIR}/google/protobuf/empty.pb-c.c")
set(GEN_C_HDRS
   "${C_OUT_DIR}/messages.pb-c.h"
   "${C_OUT_DIR}/description.pb-c.h"
   "${C_OUT_DIR}/descriptor.pb-c.h"
   "${C_OUT_DIR}/value.pb-c.h"
   "${C_OUT_DIR}/google/protobuf/any.pb-c.h"
   "${C_OUT_DIR}/google/protobuf/empty.pb-c.h")

add_custom_target(gen_proto_dirs
   COMMAND ${CMAKE_COMMAND} -E make_directory ${C_OUT_DIR}
   COMMAND ${CMAKE_COMMAND} -E make_directory ${C_OUT_DIR}/google/protobuf)

add_custom_command(
   OUTPUT ${GEN_C_SRCS} ${GEN_C_HDRS}
   BYPRODUCTS ${GEN_C_SRCS} ${GEN_C_HDRS}
   COMMAND ${Protobuf_PROTOC_EXECUTABLE} ${PROTO_INCLUDES} --c_out=${C_OUT_DIR} google/protobuf/any.proto google/protobuf/empty.proto
   COMMAND ${Protobuf_PROTOC_EXECUTABLE} ${PROTO_INCLUDES} --c_out=${C_OUT_DIR} ${BLIZZARD_PROTO_DIR}/messages.proto
   ${BLIZZARD_PROTO_DIR}/description.proto ${BLIZZARD_PROTO_DIR}/descriptor.proto ${BLIZZARD_PROTO_DIR}/value.proto
   DEPENDS gen_proto_dirs
   VERBATIM)

add_custom_target(gen_protos_c DEPENDS ${GEN_C_SRCS} ${GEN_C_HDRS})

# -------------------- Libraries --------------------
include_directories("${C_OUT_DIR}" "${C_OUT_DIR}/google" "${Protobuf_INCLUDE_DIRS}")

# C library
add_library(blizzard-c SHARED ${GEN_C_SRCS})
add_dependencies(blizzard-c gen_protos_c)
target_link_libraries(blizzard-c
   PRIVATE ${PROTOBUF_C_LIBRARIES})

set_target_properties(blizzard-c PROPERTIES LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR} OUTPUT_NAME blizzard-c)

# -------------------- pkg-config files --------------------
set(prefix ${CMAKE_INSTALL_PREFIX})
set(exec_prefix "${prefix}")
set(libdir "${exec_prefix}/lib")
set(VERSION "1.0.0")

# C pkg-config
set(includedir "${prefix}/include/blizzard/c")
set(NAME "libBlizzard-C")
set(DESCRIPTION "libBlizzard: Blizzard protobuf C library")

configure_file(blizzard.pc.in blizzard-c.pc @ONLY)

# -------------------- Install --------------------
install(
   TARGETS blizzard-c
   ARCHIVE DESTINATION lib
   LIBRARY DESTINATION lib
   RUNTIME DESTINATION bin)

install(
   DIRECTORY "${C_OUT_DIR}/"
   DESTINATION include/blizzard/c
   FILES_MATCHING
   PATTERN "*.pb-c.h")

install(FILES "${CMAKE_CURRENT_BINARY_DIR}/blizzard-c.pc" DESTINATION lib/pkgconfig)
install(FILES "${CMAKE_CURRENT_SOURCE_DIR}/blizzard_rbus_plugin.h" DESTINATION include/blizzard/c)
