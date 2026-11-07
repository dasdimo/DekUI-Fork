// SPDX-License-Identifier: GPL-2.0-or-later
package org.citra.citra_emu.utils

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Majora's Mask 3D title ids supported by this fork (see resources/mm3d/supported-rom.json). */
object TitleIds {
    const val USA = 0x0004000000125500L
    const val EUR = 0x0004000000125600L

    fun isMajoraMask3D(id: Long) = id == USA || id == EUR

    /** Directory key for mods/textures paths: lowercase 16-digit hexadecimal. */
    fun path(id: Long) = id.toString(16).padStart(16, '0')
    val all = listOf(path(USA), path(EUR))

    /** Title key of the selected ROM file, or null when it is missing or unsupported. */
    fun titleOfRom(rom: File): String? = try {
        java.io.RandomAccessFile(rom, "r").use { stream ->
            val first = ByteArray(0x130)
            stream.readFully(first)
            val base = when (String(first, 0x100, 4, Charsets.US_ASCII)) {
                "NCSD" -> (ByteBuffer.wrap(first, 0x120, 4).order(ByteOrder.LITTLE_ENDIAN).int
                    .toLong() and 0xffffffffL) shl 9
                "NCCH" -> 0L
                else -> return null
            }
            val header = ByteArray(0x120)
            stream.seek(base)
            stream.readFully(header)
            if (String(header, 0x100, 4, Charsets.US_ASCII) != "NCCH") return null
            val id = ByteBuffer.wrap(header, 0x118, 8).order(ByteOrder.LITTLE_ENDIAN).long
            path(id).takeIf { it in all }
        }
    } catch (e: Exception) {
        null
    }
}
