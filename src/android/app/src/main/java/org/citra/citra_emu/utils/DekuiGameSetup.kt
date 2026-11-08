// SPDX-License-Identifier: GPL-2.0-or-later
package org.citra.citra_emu.utils

import android.content.Context
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import org.json.JSONObject

/** Reconstructs only fingerprint-approved layout files from the selected game. */
object DekuiGameSetup {
    private fun hash(data: ByteArray) = MessageDigest.getInstance("SHA-256")
        .digest(data).joinToString("") { "%02x".format(it.toInt() and 255) }
    private fun json(context: Context, name: String) = JSONObject(
        context.assets.open("dekui-setup/$name").bufferedReader().use { it.readText() })
    private fun File.child(path: String): File {
        val result = File(this, path).canonicalFile
        require(result.path.startsWith(canonicalPath + File.separator)) { "Invalid asset path" }
        return result
    }
    fun prepare(context: Context, rom: File, root: File) {
        val roms = json(context, "supported-rom.json").getJSONArray("roms")
        require(roms.length() > 0) { "Invalid supported-rom.json" }
        val recipe = json(context, "android-layout-recipe.json")
        val inputs = recipe.getJSONObject("inputs")
        val sources = mutableMapOf<String, ByteArray>()
        var titleKey: String? = null
        var sourceDir = ""
        var archiveNames = listOf<String>()
        var messages = JSONObject()
        var rusBlock: JSONObject? = null
        RandomAccessFile(rom, "r").use { stream ->
            fun read(at: Long, count: Int): ByteArray {
                require(at >= 0 && count >= 0 && at <= stream.length() - count) { "Truncated game file" }
                return ByteArray(count).also { stream.seek(at); stream.readFully(it) }
            }
            fun u32(at: Long) = ByteBuffer.wrap(read(at, 4)).order(ByteOrder.LITTLE_ENDIAN).int.toLong() and 0xffffffffL
            require(String(read(0x100,4), Charsets.US_ASCII) == "NCSD") { "Select a decrypted .cci or .3ds game" }
            val base = u32(0x120) * 512
            val length = u32(0x124) * 512
            require(base >= 512) { "Unsupported game revision" }
            require(String(read(base + 0x100,4), Charsets.US_ASCII) == "NCCH") { "Invalid game partition" }
            require(read(base + 0x18f,1)[0].toInt() and 4 != 0) { "The selected game must be decrypted" }
            val digest = MessageDigest.getInstance("SHA-256")
            var offset = 0L
            while (offset < length) {
                val bytes = read(base + offset, minOf(1024 * 1024L, length - offset).toInt())
                digest.update(bytes); offset += bytes.size
            }
            val partitionHash = digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
            for (i in 0 until roms.length()) {
                val profile = roms.getJSONObject(i)
                if (length != profile.getLong("main_partition_bytes") ||
                    partitionHash != profile.getString("main_partition_sha256")) continue
                val programId = ByteBuffer.wrap(read(base + 0x118, 8)).order(ByteOrder.LITTLE_ENDIAN).long
                val remaster = ByteBuffer.wrap(read(base + 0x20e, 2)).order(ByteOrder.LITTLE_ENDIAN)
                    .short.toInt() and 0xffff
                require(String.format("%016x", programId) == profile.getString("title_id") &&
                    remaster == profile.getInt("remaster_version")) { "Unsupported game revision" }
                titleKey = profile.getString("title_id")
                break
            }
            require(titleKey != null) {
                "Unsupported game: select the decrypted USA or Europe (En,Fr,De,Es,It) Rev 1 version"
            }
            // The message archives and their expected reconstructions come from
            // the shipped profile for the title that was just identified. The
            // Europe profile's Russian block overrides the base when present.
            val title = json(context, "setup-fingerprints.json")
                .getJSONObject("titles").getJSONObject(titleKey!!)
            rusBlock = title.optJSONObject("rus")
            messages = rusBlock?.getJSONObject("messages") ?: title.getJSONObject("messages")
            sourceDir = messages.getString("source_dir")
            archiveNames = (0 until messages.getJSONArray("names").length())
                .map { messages.getJSONArray("names").getString(it) }
            val start = base + u32(base + 0x1b0) * 512 + 0x1000
            val romfsLength = u32(base + 0x1b4) * 512 - 0x1000
            fun rr(at: Long, count: Int): ByteArray {
                require(at >= 0 && count >= 0 && at <= romfsLength - count) { "Invalid game filesystem" }
                return read(start + at, count)
            }
            fun words(at: Long, count: Int) = ByteBuffer.wrap(rr(at,count)).order(ByteOrder.LITTLE_ENDIAN)
            val header = words(0,40)
            require(header.getInt(0) == 40) { "Unsupported game filesystem" }
            val dt = header.getInt(12).toLong(); val ft = header.getInt(28).toLong()
            val payload = header.getInt(36).toLong()
            val wanted = inputs.keys().asSequence().filter { it.startsWith("original/") }.toSet() +
                archiveNames.map { "original/$sourceDir/$it.gmsg" }
            val visited = mutableSetOf<Long>()
            fun directory(at: Long, parent: String, depth: Int): Long {
                require(depth <= 32 && visited.add(at)) { "Invalid directory tree" }
                val entry = words(dt + at,24)
                val sibling = entry.getInt(4).toLong() and 0xffffffffL
                var child = entry.getInt(8).toLong() and 0xffffffffL
                var file = entry.getInt(12).toLong() and 0xffffffffL
                val n = entry.getInt(20); require(n in 0..1024)
                val name = String(rr(dt + at + 24,n),Charsets.UTF_16LE)
                val path = parent + if (name.isEmpty()) "" else "$name/"
                val seen = mutableSetOf<Long>()
                while (file != 0xffffffffL) {
                    require(seen.add(file))
                    val f = words(ft + file,32)
                    val size = f.getLong(16); val nameSize = f.getInt(28)
                    require(nameSize in 0..1024)
                    val key = "original/romfs/" + path + String(rr(ft + file + 32,nameSize),Charsets.UTF_16LE)
                    if (key in wanted) {
                        require(size in 0..16*1024*1024L && key !in sources)
                        sources[key] = rr(payload + f.getLong(8),size.toInt())
                    }
                    file = f.getInt(4).toLong() and 0xffffffffL
                }
                while (child != 0xffffffffL) child = directory(child,path,depth+1)
                return sibling
            }
            directory(0,"",0)
            require(sources.keys == wanted) { "Required game layouts missing" }
        }
        // The Europe title's Russian overlay: every vendored file is verified
        // against its manifest; the RU message archive becomes the base the
        // expansion runs on, and the remaining files install as plain copies.
        val rusFiles = mutableMapOf<String, ByteArray>()
        if (rusBlock != null) {
            val entries = json(context, rusBlock.getString("manifest")).getJSONArray("files")
            for (i in 0 until entries.length()) {
                val entry = entries.getJSONObject(i)
                val path = entry.getString("path")
                val bytes = context.assets.open("dekui-setup/" + rusBlock.getString("manifest").substringBeforeLast('/') + "/" + path)
                    .use { it.readBytes() }
                require(bytes.size == entry.getInt("size") && hash(bytes) == entry.getString("sha256")) {
                    "Russian overlay content drifted from its manifest: $path"
                }
                rusFiles[path] = bytes
            }
            val baseDir = sourceDir.removePrefix("romfs/") + "/"
            for ((path, bytes) in rusFiles) if (path.startsWith(baseDir)) sources["original/romfs/$path"] = bytes
        }
        for (key in inputs.keys()) {
            if (key.startsWith("restoration/")) sources[key] = context.assets
                .open("dekui-setup/project-restoration/" + key.removePrefix("restoration/"))
                .use { it.readBytes() }
            require(hash(sources.getValue(key)) == inputs.getString(key)) { "Layout input mismatch: $key" }
        }
        val stage = File(root, ".dekui-setup-${java.util.UUID.randomUUID()}")
        check(stage.mkdirs())
        try {
            val mods = File(stage,"mods"); check(mods.mkdirs())
            val files = recipe.getJSONArray("files")
            for (i in 0 until files.length()) {
                val item = files.getJSONObject(i)
                val size = item.getInt("size"); require(size in 0..16*1024*1024)
                val output = sources.getValue(item.getString("base")).copyOf(size)
                val ops = item.getJSONArray("ops")
                for (j in 0 until ops.length()) {
                    val op = ops.getJSONObject(j); val at = op.getInt("at")
                    if (op.has("byte")) output[at] = op.getInt("byte").toByte()
                    else {
                        val from = op.getInt("offset"); val count = op.getInt("length")
                        sources.getValue(op.getString("copy")).copyInto(output,at,from,from+count)
                    }
                }
                require(hash(output) == item.getString("sha256")) { "Layout reconstruction mismatch" }
                val target = mods.child(item.getString("output")); target.parentFile!!.mkdirs(); target.writeBytes(output)
            }
            // Expand message storage from the verified user ROM, never from bundled game data.
            // The rus profile has no English archive at all: text.english is JSON null, so
            // the lookup must not require an object; every archived name then takes the
            // localized expansion path.
            val englishArchive = messages.getJSONObject("text").optJSONObject("english")?.getString("name")
            for (name in archiveNames) {
                var data = sources.getValue("original/$sourceDir/$name.gmsg")
                fun expand(id: Int, capacity: Int) {
                    val table = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
                    require(String(data.copyOfRange(0, 4), Charsets.US_ASCII) == "GMSG")
                    val count = table.getInt(8); require(count in 1..20000 && 16 + count * 20 <= data.size)
                    val at = (0 until count).map { 16 + it * 20 }
                        .single { table.getShort(it).toInt() and 65535 == id }
                    val offset = table.getInt(at + 12); val size = table.getInt(at + 16)
                    require(offset >= 16 + count * 20 && size in 1..capacity && offset <= data.size - size)
                    val end = (data.size + 1) and -2
                    val output = data.copyOf(end + capacity)
                    data.copyInto(output, end, offset, offset + size)
                    ByteBuffer.wrap(output).order(ByteOrder.LITTLE_ENDIAN).apply {
                        putInt(at + 12, end); putInt(at + 16, capacity)
                    }
                    data = output
                }
                // The English archive only gets the owl prompt expansion;
                // localized archives also expand the return prompt.
                if (name == englishArchive) expand(0x0c01, 1024)
                else { expand(0x0c01, 1536); expand(0x1b8a, 128) }
                require(hash(data) == messages.getJSONObject("hashes").getString(name)) { "Message reconstruction mismatch: $name" }
                val output = File(stage, "mods/$sourceDir/$name.gmsg")
                output.parentFile!!.mkdirs(); output.writeBytes(data)
            }
            // Plain mod copies of the remaining RU romfs files; generated
            // output wins (the expanded eue.gmsg was built from these bytes).
            for ((path, bytes) in rusFiles) {
                val file = mods.child("romfs/$path")
                if (!file.isFile) { file.parentFile!!.mkdirs(); file.writeBytes(bytes) }
            }
            val target = File(root,"load/mods/" + titleKey!!)
            // Retain an existing installation, including the user's edited layouts.
            if (!target.exists()) {
                target.parentFile!!.mkdirs(); check(mods.renameTo(target))
            } else {
                for (name in archiveNames) {
                    val existing = target.child("$sourceDir/$name.gmsg")
                    if (!existing.isFile) {
                        existing.parentFile!!.mkdirs()
                        File(stage, "mods/$sourceDir/$name.gmsg").copyTo(existing)
                    }
                }
                for ((path, bytes) in rusFiles) {
                    val existing = target.child("romfs/$path")
                    if (!existing.isFile) { existing.parentFile!!.mkdirs(); existing.writeBytes(bytes) }
                }

                for (i in 0 until files.length()) {
                    check(target.child(files.getJSONObject(i).getString("output")).isFile) {
                        "Existing game layouts are incomplete; existing files were retained"
                    }
                }
            }
            for ((key, bytes) in sources) if (key.startsWith("original/")) {
                val file = File(root,"config/mm3d-original").child(key.removePrefix("original/"))
                if (!file.exists()) { file.parentFile!!.mkdirs(); file.writeBytes(bytes) }
            }
        } finally { stage.deleteRecursively() }
    }
}
