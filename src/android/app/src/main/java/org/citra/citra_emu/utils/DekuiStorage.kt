// SPDX-License-Identifier: GPL-2.0-or-later
package org.citra.citra_emu.utils

import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.util.AtomicFile
import androidx.preference.PreferenceManager
import java.io.File
import org.json.JSONObject
import org.json.JSONArray
import org.citra.citra_emu.NativeLibrary

/** Shared, user-visible game data. App runtime libraries remain in app-private storage. */
object DekuiStorage {
    private const val ROOT_KEY="shared-root-path"
    fun isShared(context:Context)=context.getSharedPreferences("dekui-storage",Context.MODE_PRIVATE).getBoolean("shared-v1",false)
    fun sharedRoot()=File(Environment.getExternalStorageDirectory(),"mm3dport")
    fun hasAccess(context:Context)=if(Build.VERSION.SDK_INT>=30)Environment.isExternalStorageManager()
        else androidx.core.content.ContextCompat.checkSelfPermission(context,android.Manifest.permission.WRITE_EXTERNAL_STORAGE)==android.content.pm.PackageManager.PERMISSION_GRANTED
    fun root(context:Context):File {
        val prefs=context.getSharedPreferences("dekui-storage",Context.MODE_PRIVATE)
        if(!prefs.getBoolean("shared-v1",false)) return File(context.filesDir,"dekui")
        val configured=prefs.getString(ROOT_KEY,"").orEmpty()
        return if(configured.isNotEmpty())File(configured) else sharedRoot()
    }
    fun game(context:Context)=if(context.getSharedPreferences("dekui-storage",Context.MODE_PRIVATE).getBoolean("shared-v1",false))
        File(root(context),"game/game.cci") else File(context.filesDir,"dekui-game/game.cci")
    fun migrate(context:Context){
        check(hasAccess(context)){"Allow file access to use Internal storage/mm3dport"}
        val prefs=context.getSharedPreferences("dekui-storage",Context.MODE_PRIVATE)
        val already=prefs.getBoolean("shared-v1",false)
        val target=if(already)root(context) else sharedRoot()
        if(already) {
            check(File(target,".dekui-storage-v1").isFile){"The game data folder is missing. Restore your current folder before starting; the older private backup was retained."}
        } else DekuiStorageMigration.migrate(File(context.filesDir,"dekui"),File(context.filesDir,"dekui-game/game.cci"),target)
        check(prefs.edit().putBoolean("shared-v1",true).commit())
        check(PreferenceManager.getDefaultSharedPreferences(context).edit().putString(PermissionsHandler.CITRA_DIRECTORY,Uri.fromFile(target).toString()).commit())
        NativeLibrary.setUserDirectory(target.absolutePath)
        DirectoryInitialization.resetCitraDirectoryState()
        check(DirectoryInitialization.start()==DirectoryInitialization.DirectoryInitializationState.CITRA_DIRECTORIES_INITIALIZED){"Shared game data could not be initialized"}
        NativeLibrary.playTimeManagerInit();
        controls(context)
    }
    /** Move all shared game data to another folder on internal storage. The old root is kept as a backup.
     *  The running process keeps using the previous directory; pendingRestart tells the UI to ask for a relaunch. */
    fun changeRoot(context:Context,target:File) {
        check(hasAccess(context)){"Allow file access to move game data"}
        val prefs=context.getSharedPreferences("dekui-storage",Context.MODE_PRIVATE)
        check(prefs.getBoolean("shared-v1",false)){"Complete the first-run game setup before moving game data"}
        val storage=Environment.getExternalStorageDirectory().absolutePath
        val path=target.absolutePath
        check(path.length>storage.length+1&&path.startsWith(storage+File.separator)){"Choose a folder below Internal storage, not the storage root"}
        check(target.isDirectory||target.mkdirs()){"Cannot create the chosen game data folder"}
        DekuiStorageMigration.reparent(root(context),target)
        check(prefs.edit().putString(ROOT_KEY,target.absolutePath).commit()){"Could not store the new game data folder"}
    }
    fun pendingRestart(context:Context)=context.getSharedPreferences("dekui-storage",Context.MODE_PRIVATE)
        .getBoolean("shared-v1",false)&&root(context).absolutePath!=NativeLibrary.getUserDirectory()
    fun hasSharedBindings(context:Context):Boolean {
        val file=File(root(context),"config/android-controls.json")
        if(!file.isFile)return false
        val json=JSONObject(file.readText())
        return json.optInt("version")==1 && json.optJSONObject("bindings")?.length()?.let { it>0 }==true
    }
    private var listener:android.content.SharedPreferences.OnSharedPreferenceChangeListener?=null
    private fun bindingKey(key:String):Boolean {
        val keys=org.citra.citra_emu.features.settings.model.Settings.run { buttonKeys+triggerKeys+dPadButtonKeys+circlePadKeys+cStickKeys+dPadAxisKeys }
        return key.startsWith("InputMapping") || key in keys || key == DekuiAndroidMenu.PICTOGRAPH_KEY
    }
    private fun controls(context:Context){
        val prefs=PreferenceManager.getDefaultSharedPreferences(context)
        val file=File(root(context),"config/android-controls.json")
        listener?.let{prefs.unregisterOnSharedPreferenceChangeListener(it)}
        listener=null
        if(file.isFile){
            val json=JSONObject(file.readText());check(json.optInt("version")==1){"Unsupported controller settings version"}
            val values=json.getJSONObject("bindings");val editor=prefs.edit()
            prefs.all.keys.filter{bindingKey(it)}.forEach{editor.remove(it)}
            values.keys().forEach{key->if(bindingKey(key))when(val value=values.get(key)){
                is JSONArray->editor.putStringSet(key,(0 until value.length()).map{value.getString(it)}.toSet())
                is Int->editor.putInt(key,value)
                is Long->editor.putLong(key,value)
                is Double->editor.putFloat(key,value.toFloat())
                is Boolean->editor.putBoolean(key,value)
                is String->editor.putString(key,value)
            }}
            check(editor.commit())
        }
        org.citra.citra_emu.overlay.ReMaskedShoulderBindings.migrateLegacy(prefs)
        fun save(){
            val values=JSONObject();prefs.all.filterKeys{bindingKey(it)}.forEach{(k,v)->values.put(k,if(v is Set<*>)JSONArray(v.toList())else v)}
            val json=JSONObject().put("version",1).put("bindings",values)
            file.parentFile!!.mkdirs();val atomic=AtomicFile(file);val stream=atomic.startWrite()
            try{stream.write((json.toString(2)+"\n").toByteArray());atomic.finishWrite(stream)}catch(e:Exception){atomic.failWrite(stream);throw e}
        }
        save()
        listener?.let{prefs.unregisterOnSharedPreferenceChangeListener(it)}
        listener=android.content.SharedPreferences.OnSharedPreferenceChangeListener{_,key->if(key!=null&&bindingKey(key))save()}
        prefs.registerOnSharedPreferenceChangeListener(listener)
    }
}
