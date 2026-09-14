package edu.wellesley.scraper.ui

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import edu.wellesley.scraper.data.Prefs
import edu.wellesley.scraper.databinding.ActivityRegisterBinding
import edu.wellesley.scraper.net.ApiClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** One-time enrolment: exchange an approved email for an API key. */
class RegisterActivity : AppCompatActivity() {

    private lateinit var binding: ActivityRegisterBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityRegisterBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val prefs = Prefs(this)
        binding.backendInput.setText(prefs.backendUrl)

        binding.registerButton.setOnClickListener {
            val email = binding.emailInput.text?.toString()?.trim().orEmpty()
            val backend = binding.backendInput.text?.toString()?.trim().orEmpty()
            if (email.isEmpty() || backend.isEmpty()) {
                toast("Enter both an email and a server address")
                return@setOnClickListener
            }

            binding.registerButton.isEnabled = false
            prefs.backendUrl = backend

            lifecycleScope.launch {
                try {
                    val registration = withContext(Dispatchers.IO) {
                        ApiClient(backend).register(email, prefs.deviceId)
                    }
                    prefs.apiKey = registration.apiKey
                    prefs.participantId = registration.participantId
                    toast("Registered as ${registration.participantId}")
                    finish()
                } catch (error: ApiClient.ApiException) {
                    toast(
                        if (error.status == 403) {
                            "That email is not on the approved participant list"
                        } else {
                            "Registration failed (${error.status})"
                        }
                    )
                } catch (error: Exception) {
                    toast("Could not reach the server")
                } finally {
                    binding.registerButton.isEnabled = true
                }
            }
        }
    }

    private fun toast(message: String) =
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
}
