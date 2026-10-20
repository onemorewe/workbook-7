package dev.stas.s24lab.probe;
import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.JavascriptInterface;
public class MainActivity extends Activity {
  @Override public void onCreate(Bundle state){super.onCreate(state);WebView view=new WebView(this);view.getSettings().setJavaScriptEnabled(true);view.addJavascriptInterface(new Store(),"Probe");setContentView(view);view.loadUrl("file:///android_asset/index.html");}
  public class Store {
    @JavascriptInterface public void save(String value){getSharedPreferences("stand",0).edit().putString("value",value).commit();}
    @JavascriptInterface public String read(){return getSharedPreferences("stand",0).getString("value","");}
  }
}

