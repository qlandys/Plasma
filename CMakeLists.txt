cmake_minimum_required(VERSION 3.16)
project(PlasmaTerminal LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC ON)
set(CMAKE_AUTORCC ON)

add_executable(orderbook_backend
    backend/src/main.cpp
    backend/src/OrderBook.cpp
)

target_include_directories(orderbook_backend
    PRIVATE
        backend/include
        external/nlohmann
)

if (MSVC)
    target_compile_options(orderbook_backend PRIVATE /W4 /permissive- /MP /utf-8)
    target_link_libraries(orderbook_backend PRIVATE winhttp)
else ()
    target_compile_options(orderbook_backend PRIVATE -Wall -Wextra -Wpedantic)
    target_link_libraries(orderbook_backend PRIVATE winhttp)
endif ()

# Optional native GUI library for high-performance DOM widget.
# This requires Qt development libraries; if they are not available,
# the core backend target above still builds as before.
find_package(Qt6 COMPONENTS Widgets Gui Network WebSockets Multimedia Quick QuickWidgets Qml QUIET)
message(STATUS "Qt6_FOUND: ${Qt6_FOUND}")
if (Qt6_FOUND)
    target_link_libraries(orderbook_backend PRIVATE Qt6::Core Qt6::Network Qt6::WebSockets)
    target_compile_definitions(orderbook_backend PRIVATE ORDERBOOK_BACKEND_QT=1)

    add_executable(PlasmaTerminal
        gui_native/main.cpp
        gui_native/MainWindow.cpp
        gui_native/MainWindow.h
        gui_native/LadderClient.cpp
        gui_native/LadderClient.h
        gui_native/ConnectionStore.cpp
        gui_native/ConnectionStore.h
        gui_native/TradeManager.cpp
        gui_native/TradeManager.h
        gui_native/TradeTypes.h
        gui_native/ConnectionsWindow.cpp
        gui_native/ConnectionsWindow.h
        gui_native/TradesWindow.cpp
        gui_native/TradesWindow.h
        gui_native/FinrezWindow.cpp
        gui_native/FinrezWindow.h
        gui_native/PluginsWindow.cpp
        gui_native/PluginsWindow.h
        gui_native/SettingsWindow.cpp
        gui_native/SettingsWindow.h
        gui_native/ThemeManager.cpp
        gui_native/ThemeManager.h
        gui_native/gui_resources.qrc
        gui_native/PrintsWidget.cpp
        gui_native/PrintsWidget.h
        gui_native/ClustersWidget.cpp
        gui_native/ClustersWidget.h
        gui_native/PrintsModel.cpp
        gui_native/PrintsModel.h
        gui_native/DomWidget.cpp
        gui_native/DomWidget.h
        gui_native/DomLevelsModel.cpp
        gui_native/DomLevelsModel.h
        gui_native/SymbolPickerDialog.cpp
        gui_native/SymbolPickerDialog.h
    )
    target_link_libraries(PlasmaTerminal PRIVATE Qt6::Widgets Qt6::Gui Qt6::Network Qt6::WebSockets
                                           Qt6::Quick Qt6::QuickWidgets Qt6::Qml
                                           $<$<TARGET_EXISTS:Qt6::Multimedia>:Qt6::Multimedia>
                                           $<$<PLATFORM_ID:Windows>:Crypt32>
                                           $<$<PLATFORM_ID:Windows>:Shell32>)
    if (MSVC)
        target_compile_options(PlasmaTerminal PRIVATE /utf-8)
    endif ()
    target_include_directories(PlasmaTerminal PRIVATE external/nlohmann)
    add_dependencies(PlasmaTerminal orderbook_backend)

    # Some image editors/copy tools preserve timestamps, which can prevent MSBuild+AUTORCC
    # from regenerating the compiled resource even when the file content changed.
    # Detect changes by hash and touch the files to force an RCC rebuild only when needed.
    set(_plasma_logo_stamp "${CMAKE_BINARY_DIR}/.autogen/logo_hashes.stamp")
    add_custom_target(plasma_refresh_logos
        COMMAND "${CMAKE_COMMAND}"
            -DLOGO_BINANCE="${CMAKE_SOURCE_DIR}/img/icons/logos/binance.png"
            -DLOGO_MEXC="${CMAKE_SOURCE_DIR}/img/icons/logos/mexc.png"
            -DLOGO_UZX="${CMAKE_SOURCE_DIR}/img/icons/logos/UZX.png"
            -DSTAMP_FILE="${_plasma_logo_stamp}"
            -P "${CMAKE_SOURCE_DIR}/cmake/RefreshLogoTimestamps.cmake"
        VERBATIM
    )
    add_dependencies(PlasmaTerminal plasma_refresh_logos)

    if (WIN32)
        find_package(Python3 COMPONENTS Interpreter QUIET)
        if (Python3_Interpreter_FOUND)
            set(GHOST_PYTHON_EXE "${Python3_EXECUTABLE}")
        else ()
            set(GHOST_PYTHON_EXE python)
        endif ()

        # Pinned taskbar icons are rendered at many small sizes depending on DPI.
        # Prefer the explicit favicon assets when present; fall back to generating
        # from a large PNG if needed.
        set(GHOST_ICON_PNG "${CMAKE_SOURCE_DIR}/img/logo/favicon.ico")
        if (NOT EXISTS "${GHOST_ICON_PNG}")
            set(GHOST_ICON_PNG "${CMAKE_SOURCE_DIR}/img/logo")
        endif ()
        if (NOT EXISTS "${GHOST_ICON_PNG}")
            set(GHOST_ICON_PNG "${CMAKE_SOURCE_DIR}/img/logo/android-chrome-512x512.png")
        endif ()
        if (NOT EXISTS "${GHOST_ICON_PNG}")
            set(GHOST_ICON_PNG "${CMAKE_SOURCE_DIR}/img/logo/apple-touch-icon.png")
        endif ()
        if (NOT EXISTS "${GHOST_ICON_PNG}")
            set(GHOST_ICON_PNG "${CMAKE_SOURCE_DIR}/img/ghost_logo_256.png")
        endif ()
        if (NOT EXISTS "${GHOST_ICON_PNG}")
            set(GHOST_ICON_PNG "${CMAKE_SOURCE_DIR}/img/ghost_logo.png")
        endif ()

        set(PLASMA_ICON_ICO "${CMAKE_BINARY_DIR}/plasma.ico")
        set(PLASMA_ICON_FALLBACK "${CMAKE_SOURCE_DIR}/img/logo/favicon.ico")
        if (NOT EXISTS "${PLASMA_ICON_FALLBACK}")
            set(PLASMA_ICON_FALLBACK "")
        endif ()

        # Re-generate ghost.ico when icon assets change (CMake configure is not enough; users often
        # replace PNGs without re-running configure and Windows pinned icons appear stale).
        set(_plasma_icon_sources "${CMAKE_SOURCE_DIR}/scripts/make_windows_ico.py")
        if (IS_DIRECTORY "${GHOST_ICON_PNG}")
            file(GLOB _ghost_logo_files
                "${GHOST_ICON_PNG}/*.png"
                "${GHOST_ICON_PNG}/*.ico"
            )
            list(APPEND _plasma_icon_sources ${_ghost_logo_files})
        else ()
            list(APPEND _plasma_icon_sources "${GHOST_ICON_PNG}")
        endif ()
        list(APPEND _plasma_icon_sources "${CMAKE_SOURCE_DIR}/cmake/GenerateWindowsIcon.cmake")

        add_custom_command(
            OUTPUT "${PLASMA_ICON_ICO}"
            COMMAND "${CMAKE_COMMAND}"
                -DPYTHON_EXE=${GHOST_PYTHON_EXE}
                -DICON_INPUT=${GHOST_ICON_PNG}
                -DOUTPUT_ICO=${PLASMA_ICON_ICO}
                -DFALLBACK_ICO=${PLASMA_ICON_FALLBACK}
                -P "${CMAKE_SOURCE_DIR}/cmake/GenerateWindowsIcon.cmake"
            DEPENDS ${_plasma_icon_sources}
            VERBATIM
        )
        add_custom_target(plasma_generate_windows_icon DEPENDS "${PLASMA_ICON_ICO}")
        add_dependencies(PlasmaTerminal plasma_generate_windows_icon)

        set(PLASMA_ICON_PATH "${PLASMA_ICON_ICO}")
        file(TO_CMAKE_PATH "${PLASMA_ICON_PATH}" PLASMA_ICON_PATH)

        # MSBuild doesn't always track ICON file deps for .rc compilation. Generate the .rc
        # via a custom command that depends on the .ico so the resource is recompiled when the
        # icon changes (important for pinned taskbar icon updates).
        set(_plasma_rc "${CMAKE_BINARY_DIR}/plasma_icon.rc")
        add_custom_command(
            OUTPUT "${_plasma_rc}"
            COMMAND "${CMAKE_COMMAND}"
                -DOUTPUT_RC=${_plasma_rc}
                -DICON_PATH=${PLASMA_ICON_PATH}
                -P "${CMAKE_SOURCE_DIR}/cmake/WriteGhostRc.cmake"
            DEPENDS "${CMAKE_SOURCE_DIR}/cmake/WriteGhostRc.cmake" "${PLASMA_ICON_ICO}"
            VERBATIM
        )
        target_sources(PlasmaTerminal PRIVATE "${_plasma_rc}")
    endif ()
elseif (NOT WIN32)
    # Try Qt5 as a fallback on non-Windows platforms.
    find_package(Qt5 COMPONENTS Widgets Gui Network WebSockets Multimedia Quick QuickWidgets Qml QUIET)
    if (Qt5Widgets_FOUND)
        add_library(dom_widget STATIC
            gui_native/DomWidget.cpp
            gui_native/DomWidget.h
        )
        target_link_libraries(dom_widget PRIVATE Qt5::Widgets)
        target_compile_features(dom_widget PRIVATE cxx_std_20)

        add_executable(PlasmaTerminal
            gui_native/main.cpp
            gui_native/MainWindow.cpp
            gui_native/MainWindow.h
            gui_native/ThemeManager.cpp
            gui_native/ThemeManager.h
            gui_native/LadderClient.cpp
            gui_native/LadderClient.h
            gui_native/ConnectionStore.cpp
            gui_native/ConnectionStore.h
            gui_native/TradeManager.cpp
            gui_native/TradeManager.h
            gui_native/TradeTypes.h
            gui_native/ConnectionsWindow.cpp
            gui_native/ConnectionsWindow.h
            gui_native/TradesWindow.cpp
            gui_native/TradesWindow.h
            gui_native/FinrezWindow.cpp
            gui_native/FinrezWindow.h
        )
    target_link_libraries(PlasmaTerminal PRIVATE Qt5::Widgets Qt5::Gui Qt5::Network Qt5::WebSockets
                                           Qt5::Quick Qt5::QuickWidgets Qt5::Qml
                                           $<$<TARGET_EXISTS:Qt5::Multimedia>:Qt5::Multimedia>
                                           $<$<PLATFORM_ID:Windows>:Crypt32>
                                           $<$<PLATFORM_ID:Windows>:Shell32>
                                           dom_widget)
    target_include_directories(PlasmaTerminal PRIVATE external/nlohmann)
    endif ()
message(STATUS "Qt5Widgets_FOUND: ${Qt5Widgets_FOUND}")
endif ()
