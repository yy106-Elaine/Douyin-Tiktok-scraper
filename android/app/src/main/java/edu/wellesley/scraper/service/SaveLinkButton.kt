package edu.wellesley.scraper.service

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.provider.Settings
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import edu.wellesley.scraper.ui.ClipboardReaderActivity
import kotlin.math.abs

/**
 * A small button that floats over the other app.
 *
 * Obtaining a video id means obtaining a link, and the only way to get
 * one without software driving the platform's own share sheet is for the
 * operator to copy it. That leaves one question: what does recording it
 * cost per video. Switching apps to paste is enough friction to make a
 * long collection run unpleasant; a button already on screen is one tap.
 *
 * This is the app's own window. It reads nothing from the app beneath it
 * and performs no action in it -- it only offers somewhere to tap after
 * a person has copied something.
 */
class SaveLinkButton(private val context: Context) {

    private var view: View? = null
    private val windows =
        context.getSystemService(Context.WINDOW_SERVICE) as WindowManager

    fun isShowing(): Boolean = view != null

    /** True when the user has granted "display over other apps". */
    fun canShow(): Boolean = Settings.canDrawOverlays(context)

    fun show() {
        if (view != null || !canShow()) return

        val button = TextView(context).apply {
            text = "＋"
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 22f)
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(BUTTON_COLOR)
                setStroke(dp(2), Color.WHITE)
            }
            alpha = 0.85f
            contentDescription = "Save the copied link"
        }

        val params = WindowManager.LayoutParams(
            dp(52),
            dp(52),
            overlayType(),
            // Not focusable, so the app underneath keeps receiving
            // input; the activity this launches takes focus instead,
            // which is what makes the clipboard readable at all.
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            android.graphics.PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = dp(8)
            y = dp(220)
        }

        button.setOnTouchListener(DragOrTap(params))
        // A failed add must not leave `view` set, or show() will think
        // the button is up and never try again.
        runCatching { windows.addView(button, params) }
            .onSuccess { view = button }
            .onFailure { view = null }
    }

    fun hide() {
        view?.let {
            runCatching { windows.removeView(it) }
            view = null
        }
    }

    private fun saveCopiedLink() {
        context.startActivity(
            Intent(context, ClipboardReaderActivity::class.java).apply {
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_NO_ANIMATION or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP,
                )
            },
        )
    }

    /**
     * Distinguishes a tap from a drag, so the button can be moved out of
     * the way of whatever it is covering.
     */
    private inner class DragOrTap(
        private val params: WindowManager.LayoutParams,
    ) : View.OnTouchListener {

        private var startX = 0
        private var startY = 0
        private var touchX = 0f
        private var touchY = 0f

        override fun onTouch(view: View, event: MotionEvent): Boolean {
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    startX = params.x
                    startY = params.y
                    touchX = event.rawX
                    touchY = event.rawY
                    return true
                }

                MotionEvent.ACTION_MOVE -> {
                    params.x = startX + (event.rawX - touchX).toInt()
                    params.y = startY + (event.rawY - touchY).toInt()
                    runCatching { windows.updateViewLayout(view, params) }
                    return true
                }

                MotionEvent.ACTION_UP -> {
                    val moved = abs(event.rawX - touchX) > dp(8) ||
                        abs(event.rawY - touchY) > dp(8)
                    if (!moved) saveCopiedLink()
                    return true
                }
            }
            return false
        }
    }

    private fun dp(value: Int): Int =
        (value * context.resources.displayMetrics.density).toInt()

    private companion object {
        val BUTTON_COLOR = Color.parseColor("#2A78D6")

        @Suppress("DEPRECATION")
        fun overlayType(): Int =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                WindowManager.LayoutParams.TYPE_PHONE
            }
    }
}
